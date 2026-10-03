"""Replay all original integer decisions with births disabled and cached proposals."""

import argparse
import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from detection_quarantine_recovery import CorroboratedRecovery
from detection_streaming import decide_frame, validate_cadence


def check_cached_sources(cache, clip, baseline):
    if len(cache) != len(clip):
        raise ValueError("Proposal cache is incomplete")
    integers = {}
    for cached, source in zip(cache, clip, strict=True):
        if (
            cached["second"] != source["second"]
            or cached["publisher_frame"] != source["publisher_frame"]
            or cached["source_pixels_sha256"] != source["pixels_sha256"]
        ):
            raise ValueError("Proposal source or chronology changed")
        integer = float(cached["second"]).is_integer()
        expected = "frozen_integer_baseline" if integer else "new_half_second"
        if cached["origin"] != expected:
            raise ValueError("Cached proposal origin changed")
        if integer:
            integers[cached["second"]] = cached
    if [row["second"] for row in baseline] != list(integers):
        raise ValueError("Original integer timeline changed")
    for old in baseline:
        new = integers[old["second"]]
        if (
            new["publisher_frame"] != old["publisher_frame"]
            or new["source_pixels_sha256"] != old["source_pixels_sha256"]
            or new["boxes"] != old["raw_detector_boxes"]
        ):
            raise ValueError("Original integer proposals were not preserved exactly")
    return integers


def check_files(protocol):
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Frozen input changed: {filename}")


def replay(args):
    protocol = json.loads(args.baseline_protocol.read_text())
    cache_protocol = json.loads(args.cache_protocol.read_text())
    check_files(protocol)
    check_files(cache_protocol)
    baseline = json.loads(args.baseline.read_text())
    cache = json.loads(args.proposals.read_text())
    clip = json.loads(
        (Path(cache_protocol["inputs"]["clip"]) / "sampled.json").read_text()
    )
    if (
        not baseline["complete"]
        or baseline["stop_reason"] is not None
        or baseline["provenance"]["protocol_sha256"] != digest(args.baseline_protocol)
        or not cache["complete"]
        or cache["stop_reason"] is not None
        or cache["protocol_sha256"] != digest(args.cache_protocol)
        or cache_protocol["baseline_protocol_sha256"] != digest(args.baseline_protocol)
        or digest(args.baseline)
        != digest(Path(cache_protocol["inputs"]["baseline_predictions"]))
    ):
        raise ValueError("Both completed runs must match their frozen inputs")
    if protocol["last_processed_second"] != 1529 or protocol["processing_fps"] != 2:
        raise ValueError("Only the exposed 0–1529 control is allowed")
    validate_cadence(clip, protocol)
    integers = check_cached_sources(
        cache["timeline"], clip["rows"], baseline["timeline"]
    )
    rules = json.loads(Path(protocol["inputs"]["quarantine_protocol"]).read_text())
    slots = set(range(1, len(protocol["seeded_cows"]) + 1))
    tracker = CorroboratedRecovery(rules, sorted(slots), protocol["recovery"])
    compared = (
        "boxes",
        "objects",
        "raw_detector_boxes",
        "conflicted_ids",
        "named_track_ids",
        "reciprocal_pairs",
    )
    for old in baseline["timeline"]:
        second = old["second"]
        path = args.baseline.parent / "masks" / f"{second}.png"
        if digest(path) != old["mask_sha256"]:
            raise ValueError("Original propagated mask changed")
        mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if mask is None or mask.shape != (clip["height"], clip["width"]):
            raise ValueError("Original mask geometry differs from the source")
        current = decide_frame(
            second,
            mask,
            old["objects"],
            integers[second]["boxes"],
            tracker,
            slots,
            protocol["naming"],
        )
        for key in compared:
            if current[key] != old[key]:
                raise ValueError(f"No-birth replay differs at second {second}: {key}")
    if tracker.events != baseline["quarantine_events"]:
        raise ValueError("Quarantine event history changed")
    paths = (
        args.baseline,
        args.baseline_protocol,
        args.proposals,
        args.cache_protocol,
        Path(__file__),
    )
    report = {
        "scope": "CPU-only no-birth plumbing parity; no truth, new source pixels or model inference",
        "complete": True,
        "proposal_rows": len(cache["timeline"]),
        "integer_frames_compared": len(integers),
        "compared_exact_fields": list(compared),
        "quarantine_events_identical": True,
        "sources": {str(path): digest(path) for path in paths},
    }
    write_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "baseline",
        "baseline-protocol",
        "proposals",
        "cache-protocol",
        "output",
    ):
        parser.add_argument(f"--{option}", type=Path, required=True)
    replay(parser.parse_args())
