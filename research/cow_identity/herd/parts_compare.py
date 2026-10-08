"""Compare ways of building the herd model, from descriptions that `parts` kept.

A combination names the networks of each kind as `label:seeds`, joined by
`+`: `cattle:0,1,2+animal:3` is three networks of one kind and one of
another. The networks of a kind are averaged, each kind scores a cow by its
own nearest photographs as the application does, and the kinds are averaged.
`@share` scores a cow by her most similar 2% of photographs instead of her
two most similar; `@cap<k>` compares with at most k photographs per cow.

Every combination gets its limits by the rule the frozen preset followed:
the highest limit at which a development run of that light named a stranger
or a wrong cow, plus 0.04 by day and 0.08 at night. Those limits are then
applied to every run. A run that learned from photographs on either side of
its video is a development run.
"""

import argparse
import json
import pickle
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from app_score import preset_rules
from tune import FINAL_WITHHELD, no_competitor, replay, tracked_run

LIMITS = [round(0.40 + 0.02 * step, 2) for step in range(34)]
MARGIN = {False: 0.04, True: 0.08}


def similarity(folder, label, seed):
    saved = np.load(folder / f"{label}-s{seed}.npz")
    return saved["crops"].astype(np.float32) @ saved["photographs"].astype(np.float32).T


def scores(folder, combination):
    """Crop by cow, and the cows, for one run."""
    combination, _, way = combination.partition("@")
    owners = np.load(folder / "owners.npy")
    cows = sorted(set(owners.tolist()))
    compared = {cow: np.flatnonzero(owners == cow) for cow in cows}
    if way.startswith("cap"):
        generator = np.random.default_rng(0)
        compared = {
            cow: generator.choice(own, min(int(way[3:]), len(own)), replace=False)
            for cow, own in compared.items()
        }
    kinds = []
    for part in combination.split("+"):
        label, seeds = part.split(":")
        together = np.mean([similarity(folder, label, seed) for seed in seeds.split(",")], axis=0)
        kinds.append(
            np.stack(
                [
                    np.sort(together[:, compared[cow]], axis=1)[
                        :, -(max(2, round(0.02 * len(compared[cow]))) if way == "share" else 2) :
                    ].mean(1)
                    for cow in cows
                ],
                1,
            )
        )
    return np.mean(kinds, axis=0), cows


def paired(folder, frames, labels):
    """The run's boxes paired with the publisher's animals; the same for every combination."""
    kept = folder / "paired.pkl"
    if kept.exists():
        return pickle.loads(kept.read_bytes())
    record = json.loads((folder / "run.json").read_text())
    run = {**tracked_run(record["track"], frames, labels), "development": record["either_side"]}
    kept.write_bytes(pickle.dumps(run))
    return run


def sweep(job):
    folder, combination, frames, labels, rules = job
    run = paired(folder, frames, labels)
    values, cows = scores(folder, combination)
    run = {**run, "classes": cows, "scores": no_competitor(values)}
    rows = []
    for limit in LIMITS:
        result = replay(
            run,
            replace(rules, min_similarity=limit, min_similarity_infrared=limit),
            FINAL_WITHHELD if run["development"] else (),
        )
        rows.append(
            {
                "limit": limit,
                "coverage": result["coverage"],
                "strangers_named": result["named_withheld"] + result["unpaired_on_withheld"],
                "wrongly_named": result["wrong_enrolled"]
                + result["unpaired_on_other"]
                + result["unpaired_elsewhere"],
                "precision": result["precision"],
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+", help="Folders written by parts")
    parser.add_argument("--combination", action="append", required=True, help="name=parts")
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True, help="Folder of frame folders")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    combinations = dict(item.split("=", 1) for item in arguments.combination)
    rules = preset_rules(json.loads(arguments.preset.read_text()))
    runs = {folder: paired(folder, arguments.frames, arguments.labels) for folder in arguments.runs}
    jobs = [
        (folder, parts, arguments.frames, arguments.labels, rules)
        for parts in combinations.values()
        for folder in runs
    ]
    with ProcessPoolExecutor(4) as pool:
        swept = iter(list(pool.map(sweep, jobs)))
    result = {}
    for name, parts in combinations.items():
        rows = {folder: next(swept) for folder in runs}
        print(f"\n{name} = {parts}")
        result[name] = {"parts": parts, "limits": {}, "runs": {}}
        for light, infrared in (("day", False), ("night", True)):
            lit = [folder for folder, run in runs.items() if run["infrared"] == infrared]
            unsafe = {
                folder: max(
                    (
                        row["limit"]
                        for row in rows[folder]
                        if row["strangers_named"] or row["wrongly_named"]
                    ),
                    default=None,
                )
                for folder in lit
            }
            known = [
                limit
                for folder, limit in unsafe.items()
                if runs[folder]["development"] and limit is not None
            ]
            if not known:
                continue
            limit = round(max(known) + MARGIN[infrared], 2)
            result[name]["limits"][light] = limit
            print(f"  {light}: limit {limit:.2f}")
            for folder in lit:
                row = next(row for row in rows[folder] if row["limit"] == limit)
                result[name]["runs"][folder.name] = {
                    "light": light,
                    "development": runs[folder]["development"],
                    **row,
                    "highest_limit_with_a_stranger_or_wrong_name": unsafe[folder],
                }
                print(
                    f"    {folder.name:12s} named {row['coverage']:.1%}, "
                    f"strangers named {row['strangers_named']}, wrong {row['wrongly_named']}; "
                    f"last unsafe limit {unsafe[folder]}"
                )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
