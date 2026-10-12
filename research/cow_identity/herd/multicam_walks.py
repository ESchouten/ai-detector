"""Count a run on the passage walk by walk instead of picture by picture.

A cow of MultiCamCows2024 walks by once in a session under each camera, and
is in view for a few seconds. Whether her name stood on most of her pictures
says how soon it appeared and how long it was kept. Whether it appeared at
all is what a camera over a passage is asked: who walked by. A walk is named
when a box paired with the cow carries her name in at least one picture, and
named as another cow when one carries another's.

The names are replayed from the run's scores by the application's rules, which
gives the names it showed. Two of those rules can be changed to see what they
cost a cow that is in view for four seconds: how many pictures have to agree,
and whether a name is kept for a moment once her box touches the picture's
edge, which the application does not do.
"""

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from app_score import load_run, paired, preset_rules, replay
from ethz import DISPUTED


def walks(shown, partner, visible, enrolled):
    """How the cows that walk by were named: the enrolled ones, and the unknown ones."""
    own, other, found = Counter(), Counter(), Counter()
    for name, cow in zip(shown, partner, strict=True):
        if cow is not None:
            found[cow] += 1
            own[cow] += name == cow
            other[cow] += name is not None and name != cow
    known = sorted(cow for cow in visible if cow in enrolled)
    unknown = sorted(cow for cow in visible if cow not in enrolled and cow != DISPUTED)
    pictures = sum(visible[cow] for cow in known)
    return {
        "pictures_of_enrolled_cows": pictures,
        "pictures_that_carry_her_name": sum(own[cow] for cow in known),
        "enrolled_cows_that_walk_by": len(known),
        "named_as_herself": sum(own[cow] > 0 for cow in known),
        "named_as_another_cow": sum(other[cow] > 0 for cow in known),
        "never_found": sum(found[cow] == 0 for cow in known),
        "not_named": [cow for cow in known if own[cow] == 0],
        "unknown_cows_that_walk_by": len(unknown),
        "unknown_cows_named": [cow for cow in unknown if other[cow] > 0],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+", help="JSON written by multicam.py run")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--observations", type=int, help="Agreeing pictures, if not the preset's")
    parser.add_argument(
        "--kept-unfit", type=float, default=0, help="Seconds a name stays at the edge"
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    results = {}
    for path in arguments.runs:
        run, classes, scores = load_run(path)
        counted, (partner, visible, _, _) = paired(
            run, arguments.frames / run["video"], arguments.labels
        )
        rules = replace(preset_rules(run["preset"]), kept_unfit=arguments.kept_unfit)
        if arguments.observations:
            rules = replace(rules, min_observations=arguments.observations)
        names, _ = replay(run, classes, scores, rules)
        shown = [names[position] for position in counted]
        results[run["video"]] = walks(shown, partner, visible, set(classes))
        print(run["video"], json.dumps(results[run["video"]]))
    arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
