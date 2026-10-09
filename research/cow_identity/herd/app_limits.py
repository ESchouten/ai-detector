"""What an application run would have shown at other similarity limits.

The run recorded the similarities behind every decision, so its rules can be
replayed with another limit and nothing else changed; one limit serves both
lights here. The highest limit at which a run still names a stranger or a
wrong cow is what the preset's limits are set above.

On a development or validation video that chooses limits. On a test video it
explains a result and is not one.
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from app_score import load_run, paired, preset_rules, replay
from ethz import DISPUTED
from video_eval import tally

LIMITS = [round(0.40 + 0.02 * step, 2) for step in range(26)]


def at_limits(path, frames_directory, labels_root, ignored=frozenset()):
    run, classes, scores = load_run(path)
    counted, (partner, visible, located, around) = paired(run, frames_directory, labels_root)
    rules = preset_rules(run["preset"])
    rows = []
    for limit in LIMITS:
        names, _ = replay(
            run,
            classes,
            scores,
            replace(rules, min_similarity=limit, min_similarity_infrared=limit),
        )
        result = tally(
            [names[position] for position in counted],
            partner,
            visible,
            located,
            around,
            set(classes),
            {*ignored, DISPUTED},
        )
        rows.append(
            {
                "limit": limit,
                "coverage": result["coverage"],
                "precision": result["precision"],
                "strangers_named": result["named_withheld"] + result["unpaired_on_withheld"],
                "wrongly_named": result["wrong_enrolled"]
                + result["unpaired_on_other"]
                + result["unpaired_elsewhere"],
                "names_that_cannot_be_judged": result["unpaired_unjudged"],
            }
        )
    unsafe = [row["limit"] for row in rows if row["strangers_named"] or row["wrongly_named"]]
    return {
        "video": run["video"],
        "visible_enrolled": result["visible_enrolled"],
        "visible_withheld": result["visible_withheld"],
        "highest_limit_with_a_stranger_or_wrong_name": max(unsafe, default=None),
        "limits": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+", help="JSON written by app_run")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ignored", type=int, nargs="*", default=[])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    results = []
    for path in arguments.runs:
        video = json.loads(path.read_text())["video"]
        result = at_limits(path, arguments.frames / video, arguments.labels, set(arguments.ignored))
        results.append(result)
        print(f"{video}: last unsafe limit {result['highest_limit_with_a_stranger_or_wrong_name']}")
        for row in result["limits"]:
            print(
                f"  {row['limit']:.2f} named {row['coverage']:.1%}, strangers {row['strangers_named']}, "
                f"wrong {row['wrongly_named']}, unjudged {row['names_that_cannot_be_judged']}"
            )
    if arguments.output:
        arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
