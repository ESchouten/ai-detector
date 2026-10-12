"""What an application run would have shown under rules the application does not have.

The run recorded the similarities behind every decision, so its names can be
replayed with a rule changed and nothing else. Two rules matter to a cow that
is in view for a few seconds only: how many pictures have to agree before her
name is shown, and what becomes of the name when her box stops being
evidence, which it does the moment it touches the picture's edge. The
application drops the name then; `--kept-unfit` keeps it for some seconds
after the last whole view of her. A third matters where cows stand packed:
how long a confirmed name is held through weaker crops, because a track can
slide from one cow onto her neighbour and take the name along.

On a development or validation video this weighs a change. On a test video it
explains a result and is not one.
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from app_score import load_run, paired, preset_rules, replay
from ethz import DISPUTED
from video_eval import tally


def counted_names(run, classes, scores, rules, pairing, ignored):
    counted, (partner, visible, located, around) = pairing
    names, _ = replay(run, classes, scores, rules)
    result = tally(
        [names[position] for position in counted],
        partner,
        visible,
        located,
        around,
        set(classes),
        {*ignored, DISPUTED},
    )
    return {
        "coverage": result["coverage"],
        "precision": result["precision"],
        "named_correctly": result["correct"],
        "strangers_named": result["named_withheld"] + result["unpaired_on_withheld"],
        "wrongly_named": result["wrong_enrolled"]
        + result["unpaired_on_other"]
        + result["unpaired_elsewhere"],
        "names_that_cannot_be_judged": result["unpaired_unjudged"],
    }


def what_if(path, frames_directory, labels_root, changes, ignored=frozenset()):
    run, classes, scores = load_run(path)
    pairing = paired(run, frames_directory, labels_root)
    rules = preset_rules(run["preset"])
    return {
        "video": run["video"],
        "as_the_application_is": counted_names(run, classes, scores, rules, pairing, ignored),
        "changed": counted_names(run, classes, scores, replace(rules, **changes), pairing, ignored),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+", help="JSON written by app_run")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ignored", type=int, nargs="*", default=[])
    parser.add_argument("--observations", type=int, help="Pictures that have to agree")
    parser.add_argument("--kept-unfit", type=float, help="Seconds a name outlasts a whole view")
    parser.add_argument("--hold", type=float, help="Seconds a name is held through weaker crops")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    changes = {}
    if arguments.observations is not None:
        changes["min_observations"] = arguments.observations
    if arguments.kept_unfit is not None:
        changes["kept_unfit"] = arguments.kept_unfit
    if arguments.hold is not None:
        changes["hold"] = arguments.hold
    results = {"rules_changed": changes, "videos": []}
    for path in arguments.runs:
        video = json.loads(path.read_text())["video"]
        result = what_if(
            path, arguments.frames / video, arguments.labels, changes, set(arguments.ignored)
        )
        results["videos"].append(result)
        for label in ("as_the_application_is", "changed"):
            row = result[label]
            print(
                f"{video} {label}: named {row['coverage']:.1%}, "
                f"strangers {row['strangers_named']}, wrong {row['wrongly_named']}, "
                f"unjudged {row['names_that_cannot_be_judged']}"
            )
    arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
