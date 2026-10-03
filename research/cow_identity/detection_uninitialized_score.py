"""Score six-seed predictions against unchanged eight-animal exposed truth."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json
from detection_reserved_score import acceptance, pooled_naming, runtime_summary
from detection_sam_tracking import score
from detection_streaming_assessment import THRESHOLDS, checked_inputs
from detection_uninitialized import WINDOWS
from video_assessment import annotations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "streaming", "annotations", "source-pickle", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    protocol, value, clip = checked_inputs(args)
    if protocol["seeded_cows"] != list(range(1, 7)) or protocol[
        "uninitialized_unknown_cows"
    ] != [7, 8]:
        raise ValueError("Expected frozen six-seed exposure control")
    records, _ = annotations(args)
    windows = {
        str(window[0]): score(
            value,
            records,
            clip,
            {**protocol, "score_seconds": window},
            value["provenance"]["seed_prompts"],
            name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
        )
        for window in WINDOWS
    }
    report = {
        "scope": "Six initial named seeds, unknown7/8uninitialized but fully scored. Exposed0..1529only; not dynamic physical arrival or blind testing.",
        "protocol_sha256": digest(args.protocol),
        "streaming_sha256": digest(args.streaming),
        "conditions": windows,
        "pooled": pooled_naming(windows),
        "acceptance": {
            key: acceptance(row, THRESHOLDS) for key, row in windows.items()
        },
        "runtime": runtime_summary(value, protocol["processing_fps"]),
        "denominator": "Original truth_at includes every visible publisher identity; omitted initialization slots7/8remain unknown in VideoMetrics. Namedunmatched predictions remain errors.",
        "scorer_sha256": digest(Path(__file__)),
    }
    write_json(args.output, report)
    print(json.dumps({key: report[key] for key in ("acceptance", "pooled", "runtime")}))


if __name__ == "__main__":
    main()
