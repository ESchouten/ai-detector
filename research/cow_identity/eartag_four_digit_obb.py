"""Same exploratory four-digit rule on the completed OBB agreement cache."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from eartag_four_digit_diagnostic import line_score
from eartag_obb_evaluation import (
    CROPS,
    checked,
    final_detector,
    read_conditions,
    validate_crop_rows,
    validate_detection,
    validate_reader_crops,
)
from eartag_ocr import DATA_MANIFEST, score_image, totals

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/ear-tags"
OBB = ROOT / "eartag_obb_evaluation_protocol.json"
DETECTION = RESULTS / "obb-detection-raw.json"
RAPID = RESULTS / "obb-rapid-raw.json"
TROCR = RESULTS / "obb-trocr-raw.json"
ORIGINAL = RESULTS / "obb-development-score.json"
PREVIOUS = RESULTS / "four-digit-exploratory.json"


def freeze(path):
    files = [
        Path(__file__),
        ROOT / "eartag_four_digit_diagnostic.py",
        ROOT / "eartag_four_digit_diagnostic_protocol.json",
        ROOT / "eartag_work_numbers.py",
        ROOT / "eartag_obb_evaluation.py",
        ROOT / "eartag_ocr.py",
        ROOT / "benchmark.py",
        OBB,
        DETECTION,
        RAPID,
        TROCR,
        ORIGINAL,
        PREVIOUS,
        DATA_MANIFEST,
        CROPS / "manifest.json",
    ]
    write_json(
        path,
        {
            "scope": "RETROSPECTIVE EXPLORATORY additional cached OBB agreement row only. Same64 exposed images/all18 literal4 targets; no work-number semantics, ownership or biological identity claim. Original full-line and four-digit results preserved.",
            "files": {str(p): digest(p) for p in files},
            "rule": "Identical previous strip-only ASCII4 helper and all157 original geometry, cardinality-first polygonIoU.5, all emitted4 included. Original Rapid.95+literal same-crop correctedTrOCR agreement unchanged. Replay all original OBB condition counts before additional four-digit scoring.",
        },
    )


def validated():
    frozen = checked(OBB, "ocr")
    detection, rapid, trocr, prepared = [
        json.loads(p.read_text())
        for p in (DETECTION, RAPID, TROCR, CROPS / "manifest.json")
    ]
    validate_detection(detection, frozen, digest(OBB))
    _, training = final_detector(frozen)
    if detection["checkpoint_sha256"] != training["checkpoint_sha256"]:
        raise ValueError("Final fixed detector changed")
    for r in (rapid, trocr):
        if (
            not r["complete"]
            or r["error"] is not None
            or r["protocol_sha256"] != digest(OBB)
            or r["detector_sha256"] != digest(DETECTION)
            or r["crop_manifest_sha256"] != digest(CROPS / "manifest.json")
        ):
            raise ValueError("Reader output provenance differs")
    for rows in (rapid["rows"], prepared["rows"]):
        validate_crop_rows(rows, detection)
    validate_reader_crops(prepared["rows"], rapid["rows"], trocr["rows"])
    for r in prepared["rows"]:
        if r["issue"] is None and digest(Path(r["path"])) != r["sha256"]:
            raise ValueError("Reader crop bytes changed")
    ids = {r["id"] for r in detection["rows"]}
    truth = {
        r["id"]: r["lines"]
        for r in json.loads(DATA_MANIFEST.read_text())["rows"]
        if r["id"] in ids
    }
    if len(ids) != 64 or sum(len(r) for r in truth.values()) != 157:
        raise ValueError("Retain original64/157 source set")
    return detection, rapid, trocr, truth


def run(protocol, output):
    recipe = json.loads(protocol.read_text())
    for name, expected in recipe["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Diagnostic input changed: {name}")
    detection, rapid, trocr, truth = validated()
    original = json.loads(ORIGINAL.read_text())
    alternate = {(r["id"], r["index"]): r for r in trocr["rows"]}
    replay = {key: [] for key in read_conditions([], {})}
    pending = []
    for frame in detection["rows"]:
        key = frame["id"]
        variants = read_conditions(
            [r for r in rapid["rows"] if r["id"] == key], alternate
        )
        for condition, predictions in variants.items():
            replay[condition].append(
                {"id": key, **score_image(truth[key], predictions)}
            )
        pending.append((key, variants["literal_agreement"]))
    for condition, rows in replay.items():
        if totals(rows) != original["conditions"][condition]["totals"]:
            raise ValueError("Original all-line counter parity failed")
    rows = [
        {"id": key, **line_score(truth[key], predictions)}
        for key, predictions in pending
    ]
    total = {k: sum(r[k] for r in rows) for k in rows[0] if k not in {"id", "matches"}}
    if total["target_lines"] != 18:
        raise ValueError("All18 original literal targets remain")
    total["literal_recall"] = total["correct"] / total["target_lines"]
    total["literal_precision"] = (
        total["correct"] / total["emitted_four_digit_lines"]
        if total["emitted_four_digit_lines"]
        else None
    )
    report = {
        "protocol_sha256": digest(protocol),
        "scope": recipe["scope"],
        "rule": recipe["rule"],
        "original_all_line_counter_parity": True,
        "conditions": {"obb_literal_agreement": {"totals": total, "rows": rows}},
    }
    write_json(output, report)
    print(json.dumps(total, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Preserve prior exploratory and original outputs")
    freeze(args.protocol) if args.mode == "freeze" else run(args.protocol, args.output)
