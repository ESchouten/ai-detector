"""Compare the unchanged real-source prefix before either run's first birth."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json

FIELDS = (
    "second",
    "boxes",
    "objects",
    "raw_detector_boxes",
    "conflicted_ids",
    "named_track_ids",
    "reciprocal_pairs",
    "object_to_channel",
    "pending_proposals",
    "born_ids",
    "upstream_step",
    "mask_sha256",
    "source_pixels_sha256",
)


def mask_path(directory, row):
    name = (
        f"{row['sequence_frame']:03d}"
        if "sequence_frame" in row
        else f"{row['second']:g}"
    )
    return directory / "masks" / f"{name}.png"


def prefix_rows(before, after, directories):
    timelines = [
        value.get("all_frames", value["timeline"]) for value in (before, after)
    ]
    if [r["second"] for r in timelines[0]] != [r["second"] for r in timelines[1]]:
        raise ValueError("Both runs must retain every original input timestamp")
    births = [
        [{"second": r["second"], "ids": r["born_ids"]} for r in rows if r["born_ids"]]
        for rows in timelines
    ]
    first = min((r["second"] for rows in births for r in rows), default=float("inf"))
    rows = []
    for old, new in zip(*timelines, strict=True):
        if old["second"] >= first:
            break
        for directory, row in zip(directories, (old, new), strict=True):
            if digest(mask_path(directory, row)) != row["mask_sha256"]:
                raise ValueError("Prefix mask bytes changed")
        source_fields = (
            ("sequence_frame", "source_frame", "input_pixels_sha256", "width", "height")
            if "sequence_frame" in old
            else ("publisher_frame",)
        )
        fields = (*FIELDS, *source_fields)
        # No model timing or cache filename is compared. Unexpected pre-birth
        # SAM attempts are exposed explicitly instead of silently ignored.
        rows.append(
            {
                "second": old["second"],
                "different_fields": [k for k in fields if old[k] != new[k]],
                "sam_attempt_counts": [
                    len(old["sam_attempts"]),
                    len(new["sam_attempts"]),
                ],
            }
        )
    return rows, births, None if first == float("inf") else first


def execute(args):
    before, after = [json.loads(p.read_text()) for p in (args.baseline, args.candidate)]
    protocol = json.loads(args.protocol.read_text())
    for p, expected in protocol["files"].items():
        if digest(Path(p)) != expected:
            raise ValueError(f"Frozen candidate source changed: {p}")
    if not before["complete"] or not after["complete"]:
        raise ValueError("Prefix parity is a diagnostic of complete runs only")
    reference = protocol["comparison_baseline"]
    if (
        str(args.baseline) != reference["predictions"]
        or digest(args.baseline) != reference["predictions_sha256"]
    ):
        raise ValueError("Different comparison baseline")
    actual_protocol = after.get(
        "protocol_sha256", after.get("provenance", {}).get("protocol_sha256")
    )
    if actual_protocol != digest(args.protocol):
        raise ValueError("Candidate output belongs to another freeze")
    rows, births, first = prefix_rows(
        before, after, (args.baseline.parent, args.candidate.parent)
    )
    report = {
        "scope": "Posthoc real-prefix diagnostic only; exact cached values before either first anonymous birth, no tolerance fitting or model calls. Later closed-loop birth schedules may legitimately differ.",
        "sources": {
            str(p): digest(p)
            for p in (args.protocol, args.baseline, args.candidate, Path(__file__))
        },
        "prefix_stops_before_second": first,
        "prefix_frames": rows,
        "exact_prefix_parity": all(not r["different_fields"] for r in rows),
        "prefix_contains_sam_attempts": any(any(r["sam_attempt_counts"]) for r in rows),
        "birth_schedules": dict(zip(("original", "joint"), births, strict=True)),
    }
    if args.output.exists():
        raise ValueError("Keep previous comparison reports")
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "baseline", "candidate", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    execute(parser.parse_args())
