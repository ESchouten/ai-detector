"""Frozen rectangle-only ownership feasibility; no detector or OCR inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAFT = (
    ROOT
    / "research/cow_identity/results/2026-10-03/ear-tags/ownership-oracle-draft.json"
)
DRAFT_SHA256 = "210a0f13b8b9e95d10cfbd672e51eb18645945ce47f8dbbba2cb8453afcc28be"
IDS = ("cow1897", "cow1983", "cow2070")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(inner: list[float], outer: list[float]) -> float:
    for box in (inner, outer):
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ValueError("Finite xyxy rectangles required")
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Rectangle must have positive area")
    intersection = max(0, min(inner[2], outer[2]) - max(inner[0], outer[0])) * max(
        0, min(inner[3], outer[3]) - max(inner[1], outer[1])
    )
    return intersection / ((inner[2] - inner[0]) * (inner[3] - inner[1]))


def choices(inner: list[float], candidates: list[dict]) -> dict:
    fractions = {obj["id"]: contained(inner, obj["xyxy"]) for obj in candidates}
    accepted = [key for key, value in fractions.items() if value >= 0.9]
    return {
        "fractions": fractions,
        "candidates": accepted,
        "selected": accepted[0] if len(accepted) == 1 else None,
    }


def predict(row: dict) -> dict:
    """Read rectangle geometry/instance labels only, never attachment truth."""
    bodies = [{"id": obj["id"], "xyxy": obj["xyxy"]} for obj in row["bodies"]]
    heads = [{"id": obj["id"], "xyxy": obj["xyxy"]} for obj in row["heads"]]
    head_links = {head["id"]: choices(head["xyxy"], bodies) for head in heads}
    tags = []
    for tag in row["tags"]:
        head = choices(tag["xyxy"], heads)
        selected = head["selected"]
        tags.append(
            {
                "id": tag["id"],
                "head": head,
                "body_id": head_links[selected]["selected"] if selected else None,
            }
        )
    return {"id": row["id"], "heads": head_links, "tags": tags}


def outcome(actual: object, expected: object, uncertain: bool = False) -> str:
    if actual is None:
        return "abstained"
    if expected is None or uncertain:
        return "accepted_unverified"
    return "correct" if actual == expected else "wrong"


def score(document: dict, predictions: list[dict]) -> dict:
    tag_counts, head_counts = Counter(), Counter()
    details = []
    for row, prediction in zip(document["rows"], predictions, strict=True):
        if row["id"] != prediction["id"]:
            raise ValueError("Prediction order differs")
        heads = {head["id"]: head for head in row["heads"]}
        tags = {tag["id"]: tag for tag in row["tags"]}
        for key, link in prediction["heads"].items():
            head_counts[
                outcome(
                    link["selected"], heads[key]["body_id"], heads[key]["uncertain"]
                )
            ] += 1
        for proposed in prediction["tags"]:
            truth = tags[proposed["id"]]
            actual = (proposed["head"]["selected"], proposed["body_id"])
            expected = (truth["head_id"], truth["body_id"])
            state = outcome(
                actual if all(actual) else None,
                expected if all(expected) else None,
                truth["uncertain"],
            )
            tag_counts[state] += 1
            details.append(
                {
                    "image": row["id"],
                    "tag": proposed["id"],
                    "outcome": state,
                    "predicted_head_body": actual,
                    "annotated_head_body": expected,
                }
            )
    return {
        "tag_counts": dict(tag_counts),
        "head_counts": dict(head_counts),
        "tags": sum(len(row["tags"]) for row in document["rows"]),
        "heads": sum(len(row["heads"]) for row in document["rows"]),
        "bodies": sum(len(row["bodies"]) for row in document["rows"]),
        "details": details,
    }


def freeze(path: Path) -> None:
    if digest(DRAFT) != DRAFT_SHA256:
        raise ValueError("Reviewed draft changed")
    draft = json.loads(DRAFT.read_text())
    if tuple(row["id"] for row in draft["rows"]) != IDS:
        raise ValueError("Expected exactly the three reviewed development frames")
    files = [
        DRAFT,
        Path(__file__),
        Path(__file__).with_name("test_eartag_ownership_oracle.py"),
    ]
    for row in draft["rows"]:
        image = ROOT / row["image"]
        if digest(image) != row["image_sha256"]:
            raise ValueError("Reviewed source image changed")
        files.append(image)
        for variant in ("heads-tags", "bodies"):
            files.append(
                ROOT
                / f".cache/cow-ear-tags/ownership-oracle/{row['id']}-{variant}-overlay.png"
            )
    protocol = {
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "annotation": str(DRAFT.relative_to(ROOT)),
        "files": {str(p.relative_to(ROOT)): digest(p) for p in files},
        "review": "Root independently inspected all six overlays and clean pixels: tagged head links visibly plausible; white cow1983H1 follows B3, but B2 overlapping fragment must compete. H6 ownership unknown appropriate. Visible body extents approximate AI annotations with rails/occlusion, no inferred hidden extent; not independently human-certified field truth.",
        "rule": "Fixed >=90% tag area in exactly one head, then >=90% head area in exactly one body. All12 heads/all20 bodies compete, including uncertain fragments. No closest-owner fallback or uncertainty filtering. All11 published tags retained, multiple tags per head allowed.",
        "scope": "Three exposed low-resolution development stills; oracle annotation rectangles only, not learned localization, OCR, independent cow identities, temporal evidence or deployment performance.",
    }
    if path.exists():
        raise ValueError("Do not overwrite an existing freeze")
    path.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")


def run(protocol_path: Path, output: Path) -> None:
    protocol = json.loads(protocol_path.read_text())
    if sys.version != protocol["python"]:
        raise ValueError("Frozen interpreter differs")
    for relative, expected in protocol["files"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Frozen input changed: {relative}")
    document = json.loads((ROOT / protocol["annotation"]).read_text())
    predictions = [predict(row) for row in document["rows"]]
    result = score(document, predictions)
    result.update(
        {
            "protocol_sha256": digest(protocol_path),
            "scope": protocol["scope"],
            "predictions": predictions,
            "status": "COMPLETE_FIXED_ORACLE_RULE",
        }
    )
    if output.exists():
        raise ValueError("Do not overwrite a completed result")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("tag_counts", "head_counts", "tags", "heads", "bodies")
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.protocol)
    elif args.output is None:
        parser.error("run requires --output")
    else:
        run(args.protocol, args.output)
