"""Frozen literal reader agreement; disagreement is rejection, never correction."""

import argparse
import importlib.metadata
import json
from pathlib import Path

from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST, score_image, totals
from eartag_trocr_score import validate_rows

ROOT = Path(__file__).parent
RESULTS = ROOT / "results/2026-10-03/ear-tags"
SMALL = RESULTS / "ocr-development-raw.json"
TROCR_PROTOCOL = ROOT / "eartag_trocr_protocol.json"
OUTPUTS = {
    "original": RESULTS / "trocr-original-raw.json",
    "adapted": RESULTS / "trocr-adapted-raw.json",
}


def agreed_predictions(first, second):
    """Join the exact same fixed crop; retain only literal nonempty agreement."""
    if len(first) != len(second):
        raise ValueError("Every original predicted crop must have a second reading")
    predictions = []
    for index, (left, right) in enumerate(zip(first, second, strict=True)):
        if right["index"] != index or left["polygon"] != right["polygon"]:
            raise ValueError("Readers did not consume the same indexed polygon")
        text = left["text"].strip()
        if text and left["score"] >= 0.95 and text == right["text"].strip():
            predictions.append(left)
    return predictions


def freeze(path):
    if any(output.exists() for output in OUTPUTS.values()):
        raise ValueError("Freeze the rule before either TrOCR pilot output exists")
    recipe = json.loads(TROCR_PROTOCOL.read_text())
    inputs = [
        Path(__file__),
        ROOT / "test_eartag_reader_agreement.py",
        ROOT / "eartag_trocr_score.py",
        ROOT / "eartag_ocr.py",
        ROOT / "benchmark.py",
        ROOT / "scoring.py",
        SMALL,
        TROCR_PROTOCOL,
        Path(recipe["data"]),
        DATA_MANIFEST,
    ]
    write_json(
        path,
        {
            "status": "FROZEN_BEFORE_TROCR_PILOT_INFERENCE",
            "files": {str(p): digest(p) for p in inputs},
            "reader_protocol": str(TROCR_PROTOCOL),
            "raw_outputs": {label: str(p) for label, p in OUTPUTS.items()},
            "libraries": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "opencv-python")
            },
            "rule": "On each of the original118sameindexed predictedpolygons, require originalRapidOCRsmall score>=.95 AND nonempty literal stripped equality with TrOCR. No corrections, numberparsing, tokenconfidence, roster, majorityrule or thresholdsearch. Comparebothoriginalandfinaladapted readers; no selectionbetween them.",
            "scoring": "All64images/all157publisherlines; same cardinality-first polygonIoU>=.5 scorer after rejection. Every missingline and acceptedextra retained. No oracle localization in this diagnostic.",
            "limits": "Exposed development pilot. Readers share pixels and can share errors; agreement does not prove independence, reliable animal ownership, complete number semantics, repeatedvideo agreement or99%fieldprecision. No application assignment enabled.",
        },
    )


def execute(protocol_path, output):
    protocol = json.loads(protocol_path.read_text())
    for name, expected in protocol["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen agreement input changed: {name}")
    if {
        name: importlib.metadata.version(name) for name in protocol["libraries"]
    } != protocol["libraries"]:
        raise ValueError("Scoring environment changed")
    small = json.loads(SMALL.read_text())
    reader_protocol = Path(protocol["reader_protocol"])
    recipe = json.loads(reader_protocol.read_text())
    data = json.loads(Path(recipe["data"]).read_text())
    truth = {
        row["id"]: row["lines"] for row in json.loads(DATA_MANIFEST.read_text())["rows"]
    }
    results = {}
    raw_hashes = {}
    for label, name in protocol["raw_outputs"].items():
        path = Path(name)
        reader = json.loads(path.read_text())
        if reader["protocol_sha256"] != digest(reader_protocol):
            raise ValueError("Reader output belongs to another experiment")
        if ("training_report_sha256" in reader) != (label == "adapted"):
            raise ValueError("Wrong original/adapted reader condition")
        validate_rows(reader, data)
        rows = []
        for frame in small["rows"]:
            second = [
                row
                for row in reader["rows"]
                if row["panel"] == "detected" and row["id"] == frame["id"]
            ]
            predictions = agreed_predictions(frame["predictions"], second)
            rows.append(
                {"id": frame["id"], **score_image(truth[frame["id"]], predictions)}
            )
        results[label] = {"totals": totals(rows), "rows": rows}
        raw_hashes[name] = digest(path)
    write_json(
        output,
        {
            "status": "COMPLETE_LITERAL_AGREEMENT_DIAGNOSTIC",
            "protocol_sha256": digest(protocol_path),
            "raw_sha256": raw_hashes,
            "conditions": results,
        },
    )
    print(json.dumps({key: value["totals"] for key, value in results.items()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "score"))
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use a new immutable output path")
    freeze(args.protocol) if args.mode == "freeze" else execute(
        args.protocol, args.output
    )


if __name__ == "__main__":
    main()
