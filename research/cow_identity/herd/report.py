"""Judge scored videos against the protocol's criteria, each and pooled."""

import argparse
import json
from collections import Counter
from pathlib import Path

from video_score import COUNTS, summarise


def judge(result, criteria):
    """Which criteria one set of counts meets. Naming nobody meets none of them."""
    return {
        "precision": result["precision"] is not None
        and result["precision"] >= criteria["precision_min"],
        "coverage": result["coverage"] >= criteria["coverage_min"],
        "unknown": result["withheld_named"] is None
        or result["withheld_named"] <= criteria["withheld_named_max"],
    }


def pool(results):
    total = Counter()
    for result in results:
        total.update({key: result[key] for key in COUNTS})
    return summarise(total)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path, nargs="+", help="Written by app_score")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    criteria = json.loads(arguments.protocol.read_text())["criteria"]
    results = [json.loads(path.read_text()) for path in arguments.scores]
    videos = {}
    for result in results:
        slowest = result["seconds_per_frame"]["total"]["p95"]
        met = judge(result, criteria) | {
            "real_time": slowest <= criteria["p95_seconds_per_frame_max"]
        }
        videos[result["video"]] = {
            **{key: result[key] for key in COUNTS},
            "coverage": result["coverage"],
            "precision": result["precision"],
            "precision_conservative": result["precision_conservative"],
            "withheld_named": result["withheld_named"],
            "seconds_per_frame": result["seconds_per_frame"]["total"],
            "replay_matches_application": result["replay_matches_application"],
            "meets": met,
            "passes": all(met.values()),
        }
    pooled = pool(results)
    met = judge(pooled, criteria)
    summary = {
        "criteria": criteria,
        "videos": videos,
        "pooled": {**pooled, "meets": met, "passes": all(met.values())},
        "passes": all(video["passes"] for video in videos.values()) and all(met.values()),
    }
    arguments.output.write_text(json.dumps(summary, indent=1) + "\n")
    for name, video in {**videos, "pooled": summary["pooled"]}.items():
        print(
            f"{name}: named {video['coverage']:.4f} of {video['visible_enrolled']} visible enrolled, "
            f"precision {video['precision']:.4f} ({video['precision_conservative']:.4f} conservative), "
            f"withheld named {video['named_withheld'] + video['unpaired_on_withheld']}"
            f"/{video['visible_withheld']}, correct {video['correct']} "
            f"wrong {video['wrong_enrolled']} unpaired {video['named_unannotated']} -> "
            f"{'passes' if video['passes'] else 'FAILS'} {video['meets']}"
        )
    print("PASSES" if summary["passes"] else "FAILS")


if __name__ == "__main__":
    main()
