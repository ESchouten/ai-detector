"""Freeze ear-tag adaptation data without pilot-group or heldout leakage."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST, checked, read_image

ROOT = Path(__file__).parent
BASE = ROOT / "eartag_ocr_protocol.json"
RAW = ROOT / "results/2026-10-03/ear-tags/ocr-development-raw.json"


def training_rows(manifest, pilot):
    by_id = {row["id"]: row for row in manifest["rows"]}
    excluded = {by_id[key]["group"] for key in pilot}
    return [
        row
        for row in manifest["rows"]
        if row["split"] == "development" and row["group"] not in excluded
    ]


def crop_entries(row, lines, training):
    return [
        {
            "id": row["id"],
            "index": index,
            "polygon": line["polygon"],
            **({"text": line["text"]} if training else {}),
        }
        for index, line in enumerate(lines)
    ]


def freeze(args):
    base = checked(BASE)
    manifest = json.loads(DATA_MANIFEST.read_text())
    by_id = {row["id"]: row for row in manifest["rows"]}
    pilot = [row["id"] for row in base["raw_input"]]
    train = training_rows(manifest, pilot)
    raw = json.loads(RAW.read_text())
    if not raw["complete"] or raw["protocol_sha256"] != digest(BASE):
        raise ValueError("Require immutable original complete small-detector output")
    sources = [*train, *(by_id[key] for key in pilot)]
    panels = {
        "train": [
            entry for row in train for entry in crop_entries(row, row["lines"], True)
        ],
        "oracle": [
            entry
            for key in pilot
            for entry in crop_entries(by_id[key], by_id[key]["lines"], False)
        ],
        "detected": [
            entry
            for row in raw["rows"]
            for entry in crop_entries(row, row["predictions"], False)
        ],
    }
    if {key: len(value) for key, value in panels.items()} != {
        "train": 3243,
        "oracle": 157,
        "detected": 118,
    }:
        raise ValueError("Expected fixed training and pilot line counts")
    files = {
        **base["files"],
        str(BASE): digest(BASE),
        str(RAW): digest(RAW),
        __file__: digest(Path(__file__)),
        str(ROOT / "test_eartag_trocr_data.py"): digest(
            ROOT / "test_eartag_trocr_data.py"
        ),
    }
    write_json(
        args.protocol,
        {
            "scope": "One domain adaptation data recipe. Entire64pilotgroups removed fromdevelopment training; calibration/reserved/ambiguous images untouched. Oracle and fixedpredicted-box inputs have no text labels. No dataset-dependent augmentation or number normalization.",
            "files": files,
            "libraries": base["libraries"],
            "params": base["params"],
            "sources": [
                {
                    key: row[key]
                    for key in ("id", "image", "image_sha256", "pixels_sha256", "group")
                }
                for row in sources
            ],
            "panels": panels,
            "training_groups": sorted({r["group"] for r in train}),
            "excluded_pilot_groups": sorted({by_id[key]["group"] for key in pilot}),
            "recipe": "Verified original BGR sourcepixels; same RapidOCR get_rotate_crop_image and fixed text_cls orientation model asbaseline. Save orientation-corrected line PNG with original geometry; no textdetector/recognizer invocation. TrOCR will apply its own pinnedRGB384processor. Preserveoriginal traintext verbatim; no truncation/allowlist.",
        },
    )


def prepare(args):
    import onnxruntime
    from rapidocr import RapidOCR
    from rapidocr.utils.process_img import get_rotate_crop_image

    frozen = checked(args.protocol)
    onnxruntime.disable_telemetry_events()
    cv2.setNumThreads(2)
    engine = RapidOCR(params=frozen["params"])
    if engine.text_cls.session.session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("Orientation preparation requires CPU only")
    sources = {row["id"]: row for row in frozen["sources"]}
    result = {"protocol_sha256": digest(args.protocol), "complete": False, "panels": {}}
    args.output.mkdir(parents=True)
    for panel, entries in frozen["panels"].items():
        rows = []
        directory = args.output / panel
        directory.mkdir()
        image = None
        last_id = None
        for entry in entries:
            if entry["id"] != last_id:
                image, source_hash = read_image(sources[entry["id"]])
                last_id = entry["id"]
            points = np.asarray(entry["polygon"], np.float32).reshape(4, 2)
            crop = get_rotate_crop_image(image, points.copy())
            rotated, cls = engine.cls_and_rotate([crop])
            path = directory / f"{entry['id']}-{entry['index']}.png"
            if not cv2.imwrite(str(path), rotated[0]):
                raise OSError("Could not cache source line crop")
            rows.append(
                {
                    **entry,
                    "path": str(path),
                    "sha256": digest(path),
                    "pixels_sha256": hashlib.sha256(
                        str(rotated[0].shape).encode() + rotated[0].tobytes()
                    ).hexdigest(),
                    "source_bgr_pixels_sha256": source_hash,
                    "shape": list(rotated[0].shape),
                    "orientation": str(cls.cls_res[0][0]),
                    "orientation_score": float(cls.cls_res[0][1]),
                }
            )
        result["panels"][panel] = rows
        print(panel, len(rows), flush=True)
    result["complete"] = True
    write_json(args.output / "manifest.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "prepare"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use a new path and preserve original frozen assets")
    (freeze if args.mode == "freeze" else prepare)(args)
