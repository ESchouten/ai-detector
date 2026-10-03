"""Frozen CPU-only author versus timm synthetic pose boundary proof."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import psutil
import timm
import torch
from autocattlogger_reference_imports import load_reference

DIRECTORY = Path(".cache/cow-autocattlogger/reference")
FLIP = [2, 1, 0, 3, 6, 5, 4, 9, 8, 7]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def difference(left, right) -> dict:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    assert a.shape == b.shape
    return {
        "shape": list(a.shape),
        "finite": bool(np.isfinite(a).all() and np.isfinite(b).all()),
        "exact": bool(np.array_equal(a, b)),
        "max_abs": float(np.max(np.abs(a - b))),
        "relative_l2": float(np.linalg.norm(a - b) / max(np.linalg.norm(a), 1e-12)),
    }


def preprocess(reference, images, boxes):
    original, candidate, geometry = [], [], []
    for image, box in zip(images, boxes, strict=True):
        center, scale = reference.bbox_transforms.bbox_xyxy2cs(box[None], padding=1.25)
        points = np.array([[box[:2], box[2:], center[0]]], np.float32)
        transformed = reference.TopdownAffine((192, 256), use_udp=True).transform(
            {
                "img": image.copy(),
                "bbox_center": center.copy(),
                "bbox_scale": scale.copy(),
                "keypoints": points,
            }
        )
        adjusted = scale[0].copy()
        adjusted[0] = max(adjusted[0], adjusted[1] * 192 / 256)
        adjusted[1] = max(adjusted[1], adjusted[0] * 256 / 192)
        matrix = np.array(
            [
                [191 / adjusted[0], 0, 191 * (0.5 - center[0, 0] / adjusted[0])],
                [0, 255 / adjusted[1], 255 * (0.5 - center[0, 1] / adjusted[1])],
            ],
            np.float32,
        )
        manual = cv2.warpAffine(image, matrix, (192, 256), flags=cv2.INTER_LINEAR)
        restored = cv2.transform(
            transformed["transformed_keypoints"], cv2.invertAffineTransform(matrix)
        )
        geometry.append(
            {
                "pixels": difference(transformed["img"], manual),
                "source_points_roundtrip": difference(points, restored),
                "adjusted_scale": difference(transformed["input_scale"], adjusted),
            }
        )
        for target, pixels in ((original, transformed["img"]), (candidate, manual)):
            rgb = pixels[..., ::-1].astype(np.float32)
            normalized = (
                rgb - np.array([123.675, 116.28, 103.53], np.float32)
            ) / np.array([58.395, 57.12, 57.375], np.float32)
            target.append(np.ascontiguousarray(normalized.transpose(2, 0, 1)))
    return (
        torch.from_numpy(np.stack(original)),
        torch.from_numpy(np.stack(candidate)),
        geometry,
    )


def models(reference, config, state):
    backbone_config = dict(config["backbone"])
    backbone_config.pop("type")
    backbone_config["init_cfg"] = None
    author = reference.HRNet(**backbone_config).eval()
    author.load_state_dict(
        {
            k.removeprefix("backbone."): v
            for k, v in state.items()
            if k.startswith("backbone.")
        },
        strict=True,
    )
    head = reference.HeatmapHead(
        in_channels=48,
        out_channels=10,
        deconv_out_channels=None,
        loss={"type": reference.KeypointMSELoss, "use_target_weight": True},
    ).eval()
    head.load_state_dict(
        {k.removeprefix("head."): v for k, v in state.items() if k.startswith("head.")},
        strict=True,
    )
    candidate = timm.create_model(
        "hrnet_w48",
        pretrained=False,
        features_only=True,
        feature_location="",
        out_indices=(1,),
    ).eval()
    candidate.stage4[2].fuse_layers = torch.nn.ModuleList(
        [candidate.stage4[2].fuse_layers[0]]
    )
    candidate.stage4[2].multi_scale_output = False
    candidate.load_state_dict(author.state_dict(), strict=True)
    candidate_head = torch.nn.Conv2d(48, 10, 1).eval()
    candidate_head.load_state_dict(head.final_layer.state_dict(), strict=True)
    assert all(
        torch.equal(v, candidate.state_dict()[k])
        for k, v in author.state_dict().items()
    )
    return author, head, candidate, candidate_head


def forward(backbone, head, inputs, *, author: bool):
    captured = {}
    hooks = []

    def remember(name):
        def hook(_module, _inputs, output):
            values = output if isinstance(output, (tuple, list)) else [output]
            captured[name] = [item.detach().cpu().numpy().copy() for item in values]

        return hook

    for name in ("conv1", "layer1", "stage2", "stage3", "stage4"):
        hooks.append(getattr(backbone, name).register_forward_hook(remember(name)))
    try:
        features = backbone(inputs)
        output = head(features if author else features[0])
    finally:
        for hook in hooks:
            hook.remove()
    return output, captured


def main():
    started = time.monotonic()
    protocol_path = Path("research/cow_identity/autocattlogger_reference_protocol.json")
    protocol = json.loads(protocol_path.read_text())
    for item in protocol["files"]:
        assert digest(Path(item["path"])) == item["sha256"], item["path"]
    torch.set_num_threads(2)
    reference = load_reference()
    config = json.loads((DIRECTORY / "model-config.json").read_text())
    state = torch.load(
        ".cache/cow-autocattlogger/pose-state-only.pt",
        map_location="cpu",
        weights_only=True,
    )
    model, head, candidate, candidate_head = models(reference, config, state)
    with np.load(DIRECTORY / "inputs.npz") as data:
        original, inputs, geometry = preprocess(
            reference, data["images"], data["boxes"]
        )
    report = {
        "protocol_sha256": digest(protocol_path),
        "geometry": geometry,
        "input": difference(original.numpy(), inputs.numpy()),
        "steps": [],
    }
    assert report["input"]["exact"]
    codec = reference.UDPHeatmap(input_size=(192, 256), heatmap_size=(48, 64), sigma=2)
    with torch.inference_mode():
        for flip in (False, True):
            tensor = inputs.flip(-1) if flip else inputs
            a, stages_a = forward(model, head, tensor, author=True)
            b, stages_b = forward(candidate, candidate_head, tensor, author=False)
            branches = {
                name: [
                    difference(x, y)
                    for x, y in zip(stages_a[name], stages_b[name], strict=True)
                ]
                for name in stages_a
            }
            if flip:
                a = reference.flip_heatmaps(
                    a, FLIP, flip_mode="heatmap", shift_heatmap=False
                )
                b = b.flip(-1)[:, FLIP]
            report["steps"].append(
                {
                    "flip": flip,
                    "branches": branches,
                    "raw_or_unflipped_heatmaps": difference(a.numpy(), b.numpy()),
                }
            )
            if not flip:
                combined_a, combined_b = a, b
            else:
                combined_a = (combined_a + a) / 2
                combined_b = (combined_b + b) / 2
        report["combined_heatmaps"] = difference(combined_a.numpy(), combined_b.numpy())
        report["decoded"] = []
        for a, b in zip(combined_a.numpy(), combined_b.numpy(), strict=True):
            pa, sa = codec.decode(a)
            pb, sb = codec.decode(b)
            report["decoded"].append(
                {"coordinates": difference(pa, pb), "scores": difference(sa, sb)}
            )
    checks = [report["combined_heatmaps"]] + [
        s["raw_or_unflipped_heatmaps"] for s in report["steps"]
    ]
    checks += [
        x for s in report["steps"] for values in s["branches"].values() for x in values
    ]
    passed = all(
        x["finite"] and x["max_abs"] <= 1e-5 and x["relative_l2"] <= 1e-5
        for x in checks
    )
    passed &= all(
        x["coordinates"]["finite"]
        and x["coordinates"]["max_abs"] <= 1e-3
        and x["scores"]["max_abs"] <= 1e-5
        for x in report["decoded"]
    )
    passed &= all(
        x["pixels"]["exact"] and x["source_points_roundtrip"]["max_abs"] < 1e-3
        for x in geometry
    )
    report.update(
        status="PASS" if passed else "FAIL",
        actual_device=str(next(model.parameters()).device),
        actual_dtype=str(next(model.parameters()).dtype),
        seconds=time.monotonic() - started,
        rss_bytes=psutil.Process().memory_info().rss,
        scope="Synthetic CPU forward + published UDP decoding only; no pose accuracy or full author application parity",
    )
    assert report["rss_bytes"] < 8 * 1024**3 and report["seconds"] < 180
    path = Path(
        "research/cow_identity/results/2026-10-03/recognition/autocattlogger-reference-cpu.json"
    )
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"steps", "geometry"}},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
