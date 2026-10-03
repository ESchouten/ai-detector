"""Score completed TrOCR outputs with the original all-line geometry denominator."""

import argparse
import importlib.metadata
import json
from pathlib import Path

from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST, score_image, totals


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b))
            )
        previous = current
    return previous[-1]


def character_counts(truth, predictions, result):
    truth_used, predictions_used = set(), set()
    errors = 0
    for match in result["matches"]:
        index = match["truth_index"]
        # Original scorer embeds the exact unique prediction object in each match.
        prediction_index = next(
            i for i, row in enumerate(predictions) if row is match["prediction"]
        )
        truth_used.add(index)
        predictions_used.add(prediction_index)
        errors += edit_distance(
            truth[index]["text"].strip(), predictions[prediction_index]["text"].strip()
        )
    errors += sum(
        len(row["text"].strip()) for i, row in enumerate(truth) if i not in truth_used
    )
    errors += sum(
        len(row["text"].strip())
        for i, row in enumerate(predictions)
        if i not in predictions_used
    )
    return {
        "character_errors_including_misses_extras": errors,
        "truth_characters": sum(len(row["text"].strip()) for row in truth),
    }


def validate_rows(raw, data):
    expected = [
        (panel, row["id"], row["index"], row["sha256"], row["polygon"])
        for panel in ("oracle", "detected")
        for row in data["panels"][panel]
    ]
    actual = [
        (row["panel"], row["id"], row["index"], row["crop_sha256"], row["polygon"])
        for row in raw["rows"]
    ]
    if not raw["complete"] or raw["error"] is not None or actual != expected:
        raise ValueError("Require complete exact275 ordered pilot crops before scoring")


def score(args):
    protocol = json.loads(args.protocol.read_text())
    for name, value in protocol["files"].items():
        if digest(Path(name)) != value:
            raise ValueError(f"Frozen source changed: {name}")
    if {
        name: importlib.metadata.version(name) for name in protocol["score_libraries"]
    } != protocol["score_libraries"]:
        raise ValueError("Frozen scorer environment changed")
    data = json.loads(Path(protocol["data"]).read_text())
    raws = [json.loads(path.read_text()) for path in (args.original, args.adapted)]
    for raw in raws:
        if raw["protocol_sha256"] != digest(args.protocol):
            raise ValueError("Wrong reader protocol")
        validate_rows(raw, data)
    if "training_report_sha256" in raws[0] or "training_report_sha256" not in raws[1]:
        raise ValueError("Compare original against final adapted reader")
    truth = {
        row["id"]: row["lines"] for row in json.loads(DATA_MANIFEST.read_text())["rows"]
    }
    images = list(dict.fromkeys(row["id"] for row in data["panels"]["oracle"]))
    conditions = {}
    for label, raw in zip(("original", "adapted"), raws, strict=True):
        for panel in ("oracle", "detected"):
            rows = []
            for key in images:
                predictions = [
                    {"polygon": row["polygon"], "text": row["text"], "score": None}
                    for row in raw["rows"]
                    if row["panel"] == panel and row["id"] == key
                ]
                result = score_image(truth[key], predictions)
                rows.append(
                    {
                        "id": key,
                        **result,
                        **character_counts(truth[key], predictions, result),
                    }
                )
            result = totals(rows)
            chars = sum(row["truth_characters"] for row in rows)
            errors = sum(
                row["character_errors_including_misses_extras"] for row in rows
            )
            conditions[f"{label}_{panel}"] = {
                "totals": {
                    **result,
                    "character_errors": errors,
                    "truth_characters": chars,
                    "character_error_rate": errors / chars,
                },
                "rows": rows,
            }
    write_json(
        args.output,
        {
            "scope": "Development reader adaptation only. Oracle is conditional localization; detected uses fixed originalsmall detector polygons/misses/extras. Raw unthresholded text; token evidence is not calibrated confidence. No animal ownership or identifier-field claim.",
            "protocol_sha256": digest(args.protocol),
            "raw_sha256": {
                str(path): digest(path) for path in (args.original, args.adapted)
            },
            "conditions": conditions,
        },
    )
    print(json.dumps({name: value["totals"] for name, value in conditions.items()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--adapted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve immutable existing scores")
    score(args)
