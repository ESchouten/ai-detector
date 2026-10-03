"""Retrospective literal-four-digit scoring on already exposed cached readings."""

import argparse
import importlib.metadata
import json
from pathlib import Path

from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST, match_polygons
from eartag_reader_agreement import agreed_predictions
from eartag_trocr_score import validate_rows
from eartag_work_numbers import work_number

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/ear-tags"
OCR = ROOT / "eartag_ocr_protocol.json"
READER = ROOT / "eartag_trocr_cpu_evaluation_protocol.json"
SMALL = RESULTS / "ocr-development-raw.json"
ADAPTED = RESULTS / "trocr-cpu-corrected-raw.json"
CONDITIONS = (
    "detected_rapid_raw",
    "detected_rapid_0.95",
    "detected_adapted_trocr",
    "detected_literal_agreement",
    "oracle_adapted_trocr",
)


def line_score(lines, predictions):
    """Match emitted four-digit lines against ALL original text geometry."""
    chosen = [p for p in predictions if work_number(p["text"]) is not None]
    pairs = match_polygons(lines, chosen)
    targets = sum(work_number(row["text"]) is not None for row in lines)
    correct = wrong = outside = 0
    details = []
    for i, j, overlap in pairs:
        truth, reading = work_number(lines[i]["text"]), work_number(chosen[j]["text"])
        exact = truth is not None and truth == reading
        correct += int(exact)
        wrong += int(truth is not None and not exact)
        outside += int(truth is None)
        details.append(
            {
                "truth_index": i,
                "truth_text": lines[i]["text"],
                "reading": reading,
                "iou": overlap,
                "literal_correct": exact,
            }
        )
    return {
        "target_lines": targets,
        "emitted_four_digit_lines": len(chosen),
        "correct": correct,
        "wrong_four_digit_target": wrong,
        "extra_on_non_four_digit_truth": outside,
        "extra_unmatched": len(chosen) - len(pairs),
        "targets_not_correctly_read": targets - correct,
        "matches": details,
    }


def freeze(path):
    data = Path(json.loads(READER.read_text())["data"])
    sources = [
        Path(__file__),
        ROOT / "test_eartag_four_digit_diagnostic.py",
        ROOT / "eartag_work_numbers.py",
        ROOT / "eartag_ocr.py",
        ROOT / "eartag_reader_agreement.py",
        ROOT / "eartag_trocr_score.py",
        ROOT / "benchmark.py",
        OCR,
        READER,
        SMALL,
        ADAPTED,
        DATA_MANIFEST,
        data,
    ]
    write_json(
        path,
        {
            "scope": "RETROSPECTIVE EXPLORATORY: already exposed64 grayscale tag crops only. Literal ASCII four-digit transcription, NOT work-number semantics, biological identity, ownership or field accuracy. Original all-line studies stay unchanged. No calibration/reserved images, new model, threshold or semantic filtering.",
            "files": {str(p): digest(p) for p in sources},
            "data": str(data),
            "conditions": list(CONDITIONS),
            "libraries": {
                n: importlib.metadata.version(n)
                for n in ("numpy", "opencv-python", "scipy")
            },
            "rule": "Use existing work_number strip-only ASCII4 helper. Every emitted4 counts; match against ALL157 original line polygons with original unique cardinality-first IoU.5. All18 literal4 targets retained. Wrong4,4onother-lengthtruth,unmatched/duplicate4 all hurt precision. Do not infer missing digits, join, select largest line or discard date-like/clipped examples. Oracle row is conditional on provided true line geometry.",
        },
    )


def inputs(document):
    for name, expected in document["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Exploratory diagnostic source changed: {name}")
    if {n: importlib.metadata.version(n) for n in document["libraries"]} != document[
        "libraries"
    ]:
        raise ValueError("Scoring libraries changed")
    ocr, small = json.loads(OCR.read_text()), json.loads(SMALL.read_text())
    adapted = json.loads(ADAPTED.read_text())
    if (
        not small["complete"]
        or small["error"] is not None
        or small["protocol_sha256"] != digest(OCR)
    ):
        raise ValueError("Require original complete cached OCR")
    if [
        {k: r[k] for k in ("id", "image", "image_sha256", "pixels_sha256")}
        for r in small["rows"]
    ] != ocr["raw_input"]:
        raise ValueError("Require unchanged64 exposed source images")
    if adapted["protocol_sha256"] != digest(READER):
        raise ValueError("Require the corrected final reader cache")
    validate_rows(adapted, json.loads(Path(document["data"]).read_text()))
    ids = {r["id"] for r in small["rows"]}
    if len(ids) != 64 or {r["id"] for r in adapted["rows"]} != ids:
        raise ValueError("No additional tag groups permitted")
    truth = {
        r["id"]: r["lines"]
        for r in json.loads(DATA_MANIFEST.read_text())["rows"]
        if r["id"] in ids
    }
    if (
        sum(len(r) for r in truth.values()) != 157
        or sum(work_number(x["text"]) is not None for r in truth.values() for x in r)
        != 18
    ):
        raise ValueError("Retain all157 lines and18 literal4 targets")
    return small, adapted, truth


def run(protocol, output):
    document = json.loads(protocol.read_text())
    small, adapted, truth = inputs(document)
    results = {k: [] for k in CONDITIONS}
    for frame in small["rows"]:
        key = frame["id"]
        predicted = frame["predictions"]
        second = [
            r for r in adapted["rows"] if r["panel"] == "detected" and r["id"] == key
        ]
        variants = (
            predicted,
            [r for r in predicted if r["score"] >= 0.95],
            second,
            agreed_predictions(predicted, second),
            [r for r in adapted["rows"] if r["panel"] == "oracle" and r["id"] == key],
        )
        for condition, predictions in zip(CONDITIONS, variants, strict=True):
            results[condition].append(
                {"id": key, **line_score(truth[key], predictions)}
            )
    conditions = {}
    for condition, rows in results.items():
        totals = {
            k: sum(r[k] for r in rows) for k in rows[0] if k not in {"id", "matches"}
        }
        totals["literal_recall"] = totals["correct"] / totals["target_lines"]
        totals["literal_precision"] = (
            totals["correct"] / totals["emitted_four_digit_lines"]
            if totals["emitted_four_digit_lines"]
            else None
        )
        conditions[condition] = {"totals": totals, "rows": rows}
    write_json(
        output,
        {
            "protocol_sha256": digest(protocol),
            "scope": document["scope"],
            "rule": document["rule"],
            "conditions": conditions,
        },
    )
    print(json.dumps({k: v["totals"] for k, v in conditions.items()}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Preserve previous diagnostic outputs")
    freeze(args.protocol) if args.mode == "freeze" else run(args.protocol, args.output)
