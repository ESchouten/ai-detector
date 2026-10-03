"""Fixed synthetic author-CPU versus timm-MPS pose comparison; no cattle input."""

from __future__ import annotations

import ast
import json
import signal
import time
from itertools import zip_longest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil
import torch
from autocattlogger_reference import (
    DIRECTORY,
    FLIP,
    difference,
    digest,
    forward,
    load_reference,
    models,
    preprocess,
)

PROTOCOL = Path("research/cow_identity/autocattlogger_mps_protocol.json")
OUTPUT = Path(
    "research/cow_identity/results/2026-10-03/recognition/autocattlogger-reference-mps.json"
)


def original_source_mapper(path):
    """Execute the exact upstream non-neural method, without estimator imports."""
    source = Path(path).read_text()
    tree = ast.parse(source)
    owner = next(x for x in tree.body if isinstance(x, ast.ClassDef))
    method = next(
        x
        for x in owner.body
        if isinstance(x, ast.FunctionDef) and x.name == "add_pred_to_datasample"
    )
    text = ast.get_source_segment(source, method)
    namespace = {"zip_longest": zip_longest}
    exec(
        compile("from __future__ import annotations\n" + text, str(path), "exec"),
        namespace,
    )
    return namespace[method.name]


def coordinates(reference, mapper, points, scores, box, image):
    from mmengine.structures import InstanceData
    from mmpose.structures import PoseDataSample

    center, scale = reference.bbox_transforms.bbox_xyxy2cs(box[None], padding=1.25)
    data = reference.TopdownAffine((192, 256), use_udp=True).transform(
        {"img": image, "bbox_center": center, "bbox_scale": scale}
    )
    sample = PoseDataSample(
        metainfo={k: data[k] for k in ("input_center", "input_scale", "input_size")}
    )
    sample.gt_instances = InstanceData(bboxes=box[None].copy(), bbox_scores=np.ones(1))
    prediction = InstanceData(keypoints=points.copy(), keypoint_scores=scores.copy())
    actual = mapper(SimpleNamespace(test_cfg={}), [prediction], None, [sample])[
        0
    ].pred_instances.keypoints
    independent = (
        points / np.array(data["input_size"]) * data["input_scale"]
        + data["input_center"]
        - 0.5 * data["input_scale"]
    ).astype(points.dtype)
    return (
        actual,
        difference(actual, independent),
        data["input_scale"] / np.array(data["input_size"]),
    )


def numerical(left, right):
    result = difference(left, right)
    result["allclose"] = bool(np.allclose(left, right, atol=1e-4, rtol=1e-3))
    return result


def memory():
    torch.mps.synchronize()
    result = {
        "rss_bytes": psutil.Process().memory_info().rss,
        "mps_driver_bytes": torch.mps.driver_allocated_memory(),
        "mps_current_bytes": torch.mps.current_allocated_memory(),
    }
    if max(result.values()) > 8 * 1024**3:
        raise MemoryError("Synthetic proof exceeded 8GiB memory boundary")
    return result


def compare(reference, model, head, candidate, candidate_head, inputs):
    steps = []
    combined = [None, None]
    for flip in (False, True):
        tensor = inputs.flip(-1) if flip else inputs
        a, stages_a = forward(model, head, tensor, author=True)
        b, stages_b = forward(candidate, candidate_head, tensor.to("mps"), author=False)
        actual_device, actual_dtype = str(b.device), str(b.dtype)
        b = b.cpu()
        branches = {
            key: [
                numerical(x, y)
                for x, y in zip(stages_a[key], stages_b[key], strict=True)
            ]
            for key in stages_a
        }
        if flip:
            a = reference.flip_heatmaps(
                a, FLIP, flip_mode="heatmap", shift_heatmap=False
            )
            b = b.flip(-1)[:, FLIP]
        av, bv = a.numpy(), b.numpy()
        peaks_a = av.reshape(*av.shape[:2], -1).argmax(-1)
        peaks_b = bv.reshape(*bv.shape[:2], -1).argmax(-1)
        steps.append(
            {
                "flip": flip,
                "branches": branches,
                "heatmaps": numerical(av, bv),
                "peak_agreement": bool(np.array_equal(peaks_a, peaks_b)),
                "author_peaks": peaks_a.tolist(),
                "candidate_peaks": peaks_b.tolist(),
                "actual_device": actual_device,
                "actual_dtype": actual_dtype,
                "memory": memory(),
            }
        )
        combined = [
            (old + new) / 2 if flip else new
            for old, new in zip(combined, (av, bv), strict=True)
        ]
    return steps, combined


def decode(reference, mapper, combined, images, boxes):
    codec = reference.UDPHeatmap(input_size=(192, 256), heatmap_size=(48, 64), sigma=2)
    decoded = []
    for a, b, image, box in zip(*combined, images, boxes, strict=True):
        pa, sa = codec.decode(a)
        pb, sb = codec.decode(b)
        source_a, formula_a, scale = coordinates(reference, mapper, pa, sa, box, image)
        source_b, formula_b, _ = coordinates(reference, mapper, pb, sb, box, image)
        decoded.append(
            {
                "input_coordinates": difference(pa, pb),
                "scores": numerical(sa, sb),
                "source_coordinates": difference(source_a, source_b),
                "source_formula_author": formula_a,
                "source_formula_candidate": formula_b,
                "source_allowed_max_abs": float(0.01 * max(scale)),
                "author_input": pa.tolist(),
                "candidate_input": pb.tolist(),
                "author_source": source_a.tolist(),
                "candidate_source": source_b.tolist(),
            }
        )
    return decoded


def execute(protocol):
    torch.set_num_threads(2)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Real MPS is unavailable; CPU fallback is prohibited")
    reference = load_reference()
    config = json.loads((DIRECTORY / "model-config.json").read_text())
    state = torch.load(
        ".cache/cow-autocattlogger/pose-state-only.pt",
        map_location="cpu",
        weights_only=True,
    )
    model, head, candidate, candidate_head = models(reference, config, state)
    candidate.to("mps")
    candidate_head.to("mps")
    state_equal = all(
        torch.equal(v, candidate.state_dict()[k].cpu())
        for k, v in model.state_dict().items()
    )
    state_equal &= all(
        torch.equal(v, candidate_head.state_dict()[k].cpu())
        for k, v in head.final_layer.state_dict().items()
    )
    assert state_equal
    with np.load(DIRECTORY / "inputs.npz") as data:
        images, boxes = data["images"], data["boxes"]
    original, inputs, geometry = preprocess(reference, images, boxes)
    assert torch.equal(original, inputs)
    mapper = original_source_mapper(protocol["source_mapping_path"])
    with torch.inference_mode():
        steps, combined = compare(
            reference, model, head, candidate, candidate_head, inputs
        )
        decoded = decode(reference, mapper, combined, images, boxes)
    heatmaps = numerical(*combined)
    combined_peaks = [x.reshape(*x.shape[:2], -1).argmax(-1) for x in combined]
    peak_agreement = bool(np.array_equal(*combined_peaks))
    numerical_checks = (
        [heatmaps]
        + [s["heatmaps"] for s in steps]
        + [v for s in steps for values in s["branches"].values() for v in values]
    )
    passed = all(x["finite"] and x["allclose"] for x in numerical_checks)
    passed &= peak_agreement and all(s["peak_agreement"] for s in steps)
    passed &= all(
        x["input_coordinates"]["finite"]
        and x["input_coordinates"]["max_abs"] <= 0.01
        and x["source_coordinates"]["finite"]
        and x["source_coordinates"]["max_abs"] <= x["source_allowed_max_abs"]
        and x["source_formula_author"]["exact"]
        and x["source_formula_candidate"]["exact"]
        and x["scores"]["allclose"]
        for x in decoded
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "state_equal_before_forward": state_equal,
        "geometry": geometry,
        "steps": steps,
        "combined_heatmaps": heatmaps,
        "combined_peak_agreement": peak_agreement,
        "decoded": decoded,
        "memory": memory(),
    }


def main():
    protocol = json.loads(PROTOCOL.read_text())
    for item in protocol["files"]:
        assert digest(Path(item["path"])) == item["sha256"], item["path"]
    started = time.monotonic()

    def expired(_signal, _frame):
        raise TimeoutError("180-second synthetic comparison deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(180)
    try:
        result = execute(protocol)
    except Exception as error:
        result = {
            "status": "FAILED_OPERATION",
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        signal.alarm(0)
    result.update(
        protocol_sha256=digest(PROTOCOL),
        seconds=time.monotonic() - started,
        scope="Synthetic numerical boundary only; no cattle, training or pose-accuracy claim",
    )
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"steps", "decoded", "geometry"}
            },
            indent=2,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
