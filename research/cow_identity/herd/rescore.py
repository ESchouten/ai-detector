"""Score an application run's crops another way and replay the rules over the result.

Reads what `app_describe` kept of a run. Every way of scoring is replayed
over a range of limits, with the run's other rules unchanged: the two nearest
photographs of a cow as the test was run, her nearest 2%, the two nearest of
at most so many photographs, one cattle network in place of three, and each
kind of network alone.

A run that was already scored is looked at again here. What this shows
explains a result; it is not one.
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from app_score import preset_rules
from tune import no_competitor, replay, tracked_run

LIMITS = [round(0.50 + 0.02 * step, 2) for step in range(18)]
# Way: which descriptions, how many of a cow's nearest photographs, at most how many of hers.
WAYS = {
    "two nearest, as tested": ("both", 0, None),
    "nearest 2%": ("both", 0.02, None),
    "two nearest of at most 300": ("both", 0, 300),
    "two nearest of at most 200": ("both", 0, 200),
    "two nearest of at most 100": ("both", 0, 100),
    "one cattle network": ("one", 0, None),
    "cattle networks alone": ("cattle", 0, None),
    "second kind alone": ("animal", 0, None),
}


def scores(described, which, share, most):
    """Crop by cow, and the cows."""
    saved = np.load(described)
    crops = saved["crops"].astype(np.float32)
    photographs = saved["photographs"].astype(np.float32)
    owners = saved["owners"]
    cattle, animal = saved["parts"].tolist()
    members = cattle // 256
    columns = {
        "both": [slice(0, cattle), slice(cattle, cattle + animal)],
        # A part is scaled so that its dot product is the mean over its networks.
        "one": [slice(0, 256), slice(cattle, cattle + animal)],
        "cattle": [slice(0, cattle)],
        "animal": [slice(cattle, cattle + animal)],
    }[which]
    cows = sorted(set(owners.tolist()))
    generator = np.random.default_rng(0)
    compared = {cow: np.flatnonzero(owners == cow) for cow in cows}
    if most:
        compared = {
            cow: generator.choice(own, min(most, len(own)), replace=False)
            for cow, own in compared.items()
        }
    kinds = []
    for part in columns:
        similarity = crops[:, part] @ photographs[:, part].T
        if which == "one" and part.start == 0:
            similarity *= members
        kinds.append(
            np.stack(
                [
                    np.sort(similarity[:, compared[cow]], axis=1)[
                        :, -max(2, round(share * len(compared[cow]))) :
                    ].mean(1)
                    for cow in cows
                ],
                1,
            )
        )
    return np.mean(kinds, axis=0), cows


def sweep(job):
    described, run, rules, way = job
    values, cows = scores(described, *WAYS[way])
    run = {**run, "classes": cows, "scores": no_competitor(values)}
    rows = []
    for limit in LIMITS:
        result = replay(
            run, replace(rules, min_similarity=limit, min_similarity_infrared=limit), ()
        )
        rows.append(
            {
                "limit": limit,
                "coverage": result["coverage"],
                "strangers_named": result["named_withheld"] + result["unpaired_on_withheld"],
                "strangers_named_share": result["withheld_named"],
                "wrongly_named": result["wrong_enrolled"]
                + result["unpaired_on_other"]
                + result["unpaired_elsewhere"],
                "precision": result["precision"],
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("described", type=Path, help="Written by app_describe")
    parser.add_argument("--run", type=Path, required=True, help="JSON written by app_run")
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run = tracked_run(arguments.run, arguments.frames, arguments.labels)
    rules = preset_rules(json.loads(arguments.run.read_text())["preset"])
    jobs = [(arguments.described, run, rules, way) for way in WAYS]
    with ProcessPoolExecutor(2) as pool:
        swept = dict(zip(WAYS, pool.map(sweep, jobs), strict=True))
    for way, rows in swept.items():
        named = max((row["limit"] for row in rows if row["strangers_named"]), default=None)
        print(f"{way}: a stranger is named up to a limit of {named}")
    arguments.output.write_text(
        json.dumps(
            {
                "note": "A run that was already scored, replayed with other ways of scoring. "
                "These explain a result; they are not results.",
                "ways": swept,
            },
            indent=1,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
