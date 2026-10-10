"""Whether a herd of real size is told apart as a herd of twelve is.

Every earlier measurement had ten or twelve cows enrolled. MultiCamCows2024
has ninety, seen from the ceiling. A herd of a chosen size is confirmed from
the publisher's pictures of the first three days, taught as the application
teaches it, and asked about every walk of the two days after, of its own cows
and of the withheld ones. A picture is scored as the application scores a
crop.

This sets the detector and the tracker aside: the publisher found the cows
and followed them. Two things are counted. Picture by picture, whether a cow
resembles herself most and enough for the preset's limit. And walk by walk,
whether as many pictures in a row agree as the preset asks before it shows a
name, at one picture a second and at five.
"""

import argparse
import json
from pathlib import Path

import numpy as np

import multicam
from auxiliary import spread
from parts import teach
from parts_compare import scores

# The application's networks, numbered as it numbers its own.
NETWORKS = {"cattle": (0, 1, 2), "animal": (3,)}
COMBINATION = "cattle:0,1,2+animal:3@share"
# A walk is asked about for its first twenty seconds; a cow that stops under a camera stays longer.
LONGEST = 20 * multicam.RATE
SMALLEST = 12


def herd(size, present):
    """A herd of this size from the cows that can be enrolled; a smaller one is part of a larger."""
    enrolled = [cow for cow in present if cow not in multicam.WITHHELD]
    return sorted(np.random.default_rng(0).permutation(enrolled)[:size].tolist())


def told_apart(similarity, cows, truth, limit):
    """Picture by picture: who resembles herself, and who is similar enough for a name."""
    enrolled = np.isin(truth, cows)
    enough = similarity.max(1) >= limit
    right = np.array(cows)[similarity.argmax(1)] == truth
    return {
        "pictures_of_enrolled_cows": int(enrolled.sum()),
        "pictures_of_withheld_cows": int((~enrolled).sum()),
        "resemble_their_own_cow_most": float(right[enrolled].mean()),
        "and_are_similar_enough": float((right & enough)[enrolled].mean()),
        "resemble_another_cow_and_are_similar_enough": float((~right & enough)[enrolled].mean()),
        "withheld_that_are_similar_enough": float(enough[~enrolled].mean()),
    }


def named(resembled, enough, needed):
    """The cows that `needed` pictures in a row resemble most and enough, by first such picture."""
    names, cow, run = {}, None, 0
    for position, (candidate, passes) in enumerate(zip(resembled, enough, strict=True)):
        run = run + 1 if passes and candidate == cow else int(passes)
        cow = candidate if passes else None
        if run == needed:
            names.setdefault(candidate, position)
    return names


def walks_named(similarity, cows, rows, limit, needed, every):
    """Walk by walk, seeing one picture in `every`: named as herself, as another cow, or not."""
    resembled = np.array(cows)[similarity.argmax(1)]
    enough = similarity.max(1) >= limit
    walk = np.array([row["walk"] for row in rows])
    counts = {
        "walks_of_enrolled_cows": 0,
        "named_as_herself": 0,
        "named_as_another_cow": 0,
        "walks_of_withheld_cows": 0,
        "withheld_named": 0,
        "pictures_of_enrolled_cows": 0,
        "pictures_that_carry_her_name": 0,
    }
    for number in np.unique(walk):
        seen = np.flatnonzero(walk == number)[::every]
        truth = rows[seen[0]]["cow"]
        names = named(resembled[seen].tolist(), enough[seen].tolist(), needed)
        if truth not in cows:
            counts["walks_of_withheld_cows"] += 1
            counts["withheld_named"] += bool(names)
            continue
        counts["walks_of_enrolled_cows"] += 1
        counts["named_as_herself"] += truth in names
        counts["named_as_another_cow"] += any(cow != truth for cow in names)
        counts["pictures_of_enrolled_cows"] += len(seen)
        # A name is held to the end of the walk once it is shown.
        counts["pictures_that_carry_her_name"] += len(seen) - names[truth] if truth in names else 0
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pictures", type=Path, help="MultiCamCows2024Root")
    parser.add_argument("--cows", type=int, required=True, help="Enrolled cows in the herd")
    parser.add_argument("--per-walk", type=int, default=8, help="Photographs confirmed of a walk")
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--herd-weights", type=Path, required=True)
    parser.add_argument("--animal-weights", type=Path, required=True, help="MIEWid as published")
    parser.add_argument("--work", type=Path, required=True, help="Keeps what was described")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    identity = json.loads(arguments.preset.read_text())["identity"]
    limit, needed = identity["min_similarity"], identity["min_observations"]
    # Only a cow that walked by on the first three days has photographs to confirm.
    present = sorted(
        {
            walk["cow"]
            for walk in multicam.walks(arguments.pictures, multicam.PHOTOGRAPHS, multicam.COWS)
        }
    )
    enrolled = herd(arguments.cows, present)
    photographs = [
        {"path": str(file.relative_to(arguments.pictures)), "cow": walk["cow"]}
        for walk in multicam.walks(arguments.pictures, multicam.PHOTOGRAPHS, enrolled)
        for file in spread(walk["files"], arguments.per_walk)
    ]
    asked = sorted({*enrolled, *multicam.WITHHELD})
    rows = [
        {"path": file, "cow": walk["cow"], "camera": walk["camera"], "walk": number}
        for number, walk in enumerate(
            multicam.walks(arguments.pictures, multicam.VALIDATION, asked)
        )
        for file in walk["files"][:LONGEST]
    ]
    arguments.work.mkdir(parents=True, exist_ok=True)
    teach(
        photographs,
        arguments.pictures,
        [row["path"] for row in rows],
        NETWORKS,
        {"cattle": arguments.herd_weights, "animal": arguments.animal_weights},
        arguments.work,
    )
    similarity, cows = scores(arguments.work, COMBINATION)
    truth = np.array([row["cow"] for row in rows])
    camera = np.array([row["camera"] for row in rows])
    smallest = np.isin(truth, [*herd(SMALLEST, present), *multicam.WITHHELD])
    per_cow = [sum(row["cow"] == cow for row in photographs) for cow in cows]
    result = {
        "enrolled_cows": cows,
        "withheld_cows": list(multicam.WITHHELD),
        "photographs": len(photographs),
        "photographs_a_cow": [min(per_cow), max(per_cow)],
        "limit": limit,
        "pictures_in_a_row": needed,
        "all": told_apart(similarity, cows, truth, limit),
        "cows_of_the_smallest_herd": told_apart(similarity[smallest], cows, truth[smallest], limit),
        "by_camera": {
            str(number): told_apart(
                similarity[camera == number], cows, truth[camera == number], limit
            )
            for number in sorted(set(camera.tolist()))
        },
        "at_other_limits": {
            str(other): told_apart(similarity, cows, truth, other)
            for other in (0.5, 0.54, 0.58, 0.6, 0.62, 0.66, 0.68, 0.7, 0.74, 0.78)
        },
        "walks_at_one_picture_a_second": walks_named(
            similarity, cows, rows, limit, needed, multicam.RATE
        ),
        "walks_at_five_pictures_a_second": walks_named(similarity, cows, rows, limit, needed, 1),
    }
    arguments.output.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({key: result[key] for key in result if key != "at_other_limits"}, indent=1))


if __name__ == "__main__":
    main()
