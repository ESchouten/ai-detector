"""Fixed native-orientation visual feasibility pilot; no identity truth or tuning."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from autocattlogger_mps import coordinates, memory, original_source_mapper
from autocattlogger_reference import (
    DIRECTORY,
    FLIP,
    digest,
    load_reference,
    models,
    preprocess,
)

OUTPUT = Path(".cache/cow-autocattlogger/pose-pilot")
PROTOCOL = Path("research/cow_identity/autocattlogger_pose_pilot_protocol.json")
RAW = Path(".cache/cow-cutie/actual-seed-corroborator.json")
CLIP = Path(".cache/cow-cutie/calibration-clip")
SECONDS = (75, 225, 375, 525)
NAMES = (
    "left_shoulder",
    "withers",
    "right_shoulder",
    "center_back",
    "left_hip_bone",
    "hip_connector",
    "right_hip_bone",
    "left_pin_bone",
    "tail_head",
    "right_pin_bone",
)


def pixels_hash(image):
    result = hashlib.sha256(str((image.shape, image.dtype)).encode())
    result.update(image.tobytes())
    return result.hexdigest()


def selected_indices(boxes):
    ordered = sorted(
        range(len(boxes)),
        key=lambda i: (
            boxes[i]["x1"] + boxes[i]["x2"],
            boxes[i]["y1"] + boxes[i]["y2"],
            i,
        ),
    )
    if len(ordered) <= 4:
        return ordered
    return [ordered[i * (len(ordered) - 1) // 3] for i in range(4)]


def prepare():
    if (OUTPUT / "selection.json").exists():
        raise ValueError("Preserve the original selection")
    raw = json.loads(RAW.read_text())
    manifest = json.loads((CLIP / "sampled.json").read_text())
    assert raw["complete"] and raw["provenance"]["sampled_manifest_sha256"] == digest(
        CLIP / "sampled.json"
    )
    assert digest(CLIP / "sampled.avi") == manifest["clip_sha256"]
    by_time = {r["second"]: r for r in raw["timeline"]}
    capture = cv2.VideoCapture(str(CLIP / "sampled.avi"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for second in SECONDS:
            index = next(
                i for i, r in enumerate(manifest["rows"]) if r["second"] == second
            )
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, image = capture.read()
            assert ok
            source = manifest["rows"][index]
            evidence = by_time[second]
            assert source["publisher_frame"] == evidence["publisher_frame"]
            assert (
                pixels_hash(image)
                == source["pixels_sha256"]
                == evidence["source_pixels_sha256"]
            )
            image_path = OUTPUT / f"frame-{second}.png"
            assert cv2.imwrite(str(image_path), image)
            indices = selected_indices(evidence["boxes"])
            rows.append(
                {
                    "second": second,
                    "sampled_index": index,
                    "publisher_frame": source["publisher_frame"],
                    "pixels_sha256": source["pixels_sha256"],
                    "image": str(image_path),
                    "image_sha256": digest(image_path),
                    "shape": list(image.shape),
                    "raw_count": len(evidence["boxes"]),
                    "selected_indices": indices,
                    "missing_budget_slots": 4 - len(indices),
                    "raw_boxes": evidence["boxes"],
                }
            )
    finally:
        capture.release()
    selection = {
        "status": "FROZEN_SELECTION_BEFORE_POSE",
        "seconds": list(SECONDS),
        "raw_sha256": digest(RAW),
        "sampled_manifest_sha256": digest(CLIP / "sampled.json"),
        "rows": rows,
    }
    (OUTPUT / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    print(
        json.dumps(
            {
                "selected": sum(len(r["selected_indices"]) for r in rows),
                "raw_counts": [r["raw_count"] for r in rows],
            }
        )
    )


def source_items(selection):
    result = []
    for row in selection["rows"]:
        image = cv2.imread(row["image"])
        assert digest(Path(row["image"])) == row["image_sha256"]
        assert pixels_hash(image) == row["pixels_sha256"]
        for index in row["selected_indices"]:
            b = row["raw_boxes"][index]
            result.append(
                (
                    row,
                    index,
                    image,
                    np.array([b[k] for k in ("x1", "y1", "x2", "y2")], np.float32),
                )
            )
    return result


def infer():
    protocol = json.loads(PROTOCOL.read_text())
    for path, sha in protocol["files"].items():
        assert digest(Path(path)) == sha, path
    target = OUTPUT / "predictions.json"
    if target.exists():
        raise ValueError("Preserve original predictions")
    assert torch.backends.mps.is_available()
    started = time.monotonic()
    torch.set_num_threads(2)
    reference = load_reference()
    state = torch.load(
        ".cache/cow-autocattlogger/pose-state-only.pt",
        map_location="cpu",
        weights_only=True,
    )
    author, head, model, candidate_head = models(
        reference, json.loads((DIRECTORY / "model-config.json").read_text()), state
    )
    del author, head, state
    model.to("mps")
    candidate_head.to("mps")
    mapper = original_source_mapper(protocol["source_mapping_path"])
    codec = reference.UDPHeatmap(input_size=(192, 256), heatmap_size=(48, 64), sigma=2)
    selection = json.loads((OUTPUT / "selection.json").read_text())
    items = source_items(selection)
    results, resources = [], []
    with torch.inference_mode():
        for start in range(0, len(items), 2):
            batch = items[start : start + 2]
            inputs, _, _ = preprocess(
                reference, [x[2] for x in batch], [x[3] for x in batch]
            )
            inputs = inputs.to("mps")
            a = candidate_head(model(inputs)[0])
            b = candidate_head(model(inputs.flip(-1))[0]).flip(-1)[:, FLIP]
            heatmaps = ((a + b) / 2).cpu().numpy()
            for (row, index, image, box), heatmap in zip(batch, heatmaps, strict=True):
                points, scores = codec.decode(heatmap)
                source, formula, _ = coordinates(
                    reference, mapper, points, scores, box, image
                )
                assert formula["exact"]
                results.append(
                    {
                        "second": row["second"],
                        "raw_index": index,
                        "input_points": points.tolist(),
                        "source_points": source.tolist(),
                        "scores": scores.tolist(),
                        "finite": bool(
                            np.isfinite(source).all() and np.isfinite(scores).all()
                        ),
                        "heatmap_sha256": hashlib.sha256(heatmap.tobytes()).hexdigest(),
                    }
                )
            resources.append(memory())
            if time.monotonic() - started > 180:
                raise TimeoutError("180-second pilot limit")
    report = {
        "status": "COMPLETE_NATIVE_POSE_BEFORE_VISUAL_REVIEW",
        "protocol_sha256": digest(PROTOCOL),
        "selection_sha256": digest(OUTPUT / "selection.json"),
        "actual_device": str(next(model.parameters()).device),
        "actual_dtype": str(next(model.parameters()).dtype),
        "seconds": time.monotonic() - started,
        "resources": resources,
        "keypoint_names": list(NAMES),
        "rows": results,
        "scope": "Selected actual body proposals only, no all-visible denominator or biological identity score",
    }
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "rows": len(results),
                "seconds": report["seconds"],
                "finite_rows": sum(r["finite"] for r in results),
            }
        )
    )


def render_inputs():
    selection = json.loads((OUTPUT / "selection.json").read_text())
    for row, index, image, box in source_items(selection):
        canvas = image.copy()
        cv2.rectangle(
            canvas,
            tuple(box[:2].astype(int)),
            tuple(box[2:].astype(int)),
            (0, 220, 255),
            2,
        )
        cv2.putText(
            canvas,
            f"t={row['second']} raw={index} | original body proposal; no pose",
            (8, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
        )
        x1, y1, x2, y2 = box.astype(int)
        crop = image[y1:y2, x1:x2]
        factor = min(400 / crop.shape[1], 540 / crop.shape[0])
        enlarged = cv2.resize(
            crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_NEAREST
        )
        panel = np.full((image.shape[0], 420, 3), 30, np.uint8)
        panel[40 : 40 + enlarged.shape[0], 10 : 10 + enlarged.shape[1]] = enlarged
        cv2.putText(
            panel,
            "Exact box crop",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
        )
        assert cv2.imwrite(
            str(OUTPUT / f"input-{row['second']}-{index}.png"),
            np.concatenate((canvas, panel), axis=1),
        )


def render():
    selection = json.loads((OUTPUT / "selection.json").read_text())
    predictions = json.loads((OUTPUT / "predictions.json").read_text())
    assert predictions["selection_sha256"] == digest(OUTPUT / "selection.json")
    items = source_items(selection)
    for item, prediction in zip(items, predictions["rows"], strict=True):
        row, index, image, box = item
        assert (row["second"], index) == (prediction["second"], prediction["raw_index"])
        canvas = image.copy()
        cv2.rectangle(
            canvas,
            tuple(box[:2].astype(int)),
            tuple(box[2:].astype(int)),
            (0, 220, 255),
            2,
        )
        for i, (point, _score) in enumerate(
            zip(prediction["source_points"][0], prediction["scores"][0], strict=True)
        ):
            if np.isfinite(point).all():
                pixel = tuple(np.rint(point).astype(int))
                cv2.circle(canvas, pixel, 3, (255, 0, 255), -1)
                cv2.putText(
                    canvas,
                    str(i),
                    pixel,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (255, 255, 255),
                    1,
                )
        caption = f"t={row['second']} raw={index} | native orientation | indices0-9; no confidence filter"
        cv2.putText(
            canvas, caption, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1
        )
        assert cv2.imwrite(str(OUTPUT / f"pose-{row['second']}-{index}.png"), canvas)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "inputs", "infer", "render"))
    {"prepare": prepare, "inputs": render_inputs, "infer": infer, "render": render}[
        parser.parse_args().command
    ]()
