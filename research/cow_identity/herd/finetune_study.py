"""Development study: adapt a backbone to the herd, then name later days.

Uses the same rotation of left-out cows and the same day splits as the frozen
descriptor study, so the two are directly comparable. Descriptors of every
development crop are saved per run; rescoring never retrains.
"""

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import torch

from crop_study import SPLITS, WITHHELD
from ethz import development_rows
from finetune import describe, directions, run_key, train
from openset import best_possible, gallery_scores, top_two


def run(rows, root, split, unknown, settings, cache, others=None):
    (first, last), (query_first, query_last) = SPLITS[split]
    cow = np.array([row["cow"] for row in rows])
    day = np.array([row["date"] for row in rows])
    paths = [str(root / row["path"]) for row in rows]
    training = ~np.isin(cow, unknown) & (day >= first) & (day <= last)
    query = (day >= query_first) & (day <= query_last)
    train_paths = [path for path, keep in zip(paths, training, strict=True) if keep]
    train_labels = cow[training].tolist()
    key = run_key(train_paths, train_labels, settings)
    store = Path(cache) / f"finetune-{key}.npz"
    if store.exists():
        saved = np.load(store)
        vectors, weights, classes = saved["vectors"], saved["directions"], saved["classes"].tolist()
    else:
        network, classes = train(
            train_paths,
            train_labels,
            others=others,
            **{key: value for key, value in settings.items() if key != "others"},
        )
        vectors = describe(network, paths, settings["size"])
        weights = directions(network)
        Path(cache).mkdir(parents=True, exist_ok=True)
        np.savez(store, vectors=vectors, directions=weights, classes=np.array(classes))
        del network
        torch.mps.empty_cache()
    truth = np.where(np.isin(cow[query], unknown), -1, cow[query])
    known = truth >= 0
    result = {
        "split": split,
        "left_out": [int(animal) for animal in unknown],
        "settings": settings,
        "run": key,
        "training_crops": int(training.sum()),
        "known": int(known.sum()),
        "unknown": int((~known).sum()),
    }
    everything = vectors[query] @ weights.T
    real, impostors = everything[:, : len(classes)], everything[:, len(classes) :]
    scorers = {
        "direction": (real, impostors),
        "gallery": (
            gallery_scores(vectors[training], cow[training], classes, vectors[query]),
            None,
        ),
    }
    for name, (scores, rivals) in scorers.items():
        winner, best, lead = top_two(scores, rivals)
        right = known & (np.asarray(classes)[winner] == truth)
        result[name] = {
            "rank1": float(right[known].mean()),
            "best_possible": best_possible(scores, truth, classes, rivals),
            "separation": separation(best, lead, right, ~known),
        }
    return result


def separation(best, lead, right, unknown):
    """How well each number tells rightly named crops from unknown animals."""

    def area(values):
        positive, negative = values[right], values[unknown]
        return float((positive[:, None] > negative[None, :]).mean())

    def kept(values, share=0.05):
        limit = np.quantile(values[unknown], 1 - share)
        return float((values[right] > limit).mean())

    return {
        "best_area": area(best),
        "lead_area": area(lead),
        "right_kept_at_5pct_unknown_best": kept(best),
        "right_kept_at_5pct_unknown_lead": kept(lead),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--backbone", default="dinov2-s")
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--rate", type=float, default=3e-5)
    parser.add_argument("--margin", type=float, default=0.25)
    parser.add_argument("--scale", type=float, default=24.0)
    parser.add_argument("--turn", type=float, default=20.0)
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument("--head-rate", type=float, default=1e-3)
    parser.add_argument("--others", type=Path, help="Manifest of other farms' cows")
    parser.add_argument("--start", type=Path, help="Checkpoint written by pretrain.py")
    parser.add_argument("--anchor", action="store_true", help="Keep its cows as rivals")
    parser.add_argument("--split", nargs="+", default=list(SPLITS))
    parser.add_argument("--rotations", type=int, default=2)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    rows = [
        row
        for row in development_rows(json.loads(arguments.manifest.read_text()))
        if row["cow"] not in WITHHELD
    ]
    cows = sorted({row["cow"] for row in rows})
    triples = list(combinations(cows, 3))
    chosen = [
        triples[i]
        for i in np.random.default_rng(0).choice(len(triples), size=arguments.rotations, replace=False)
    ]
    settings = {
        "backbone": arguments.backbone,
        "size": arguments.size,
        "epochs": arguments.epochs,
        "rate": arguments.rate,
        "margin": arguments.margin,
        "scale": arguments.scale,
        "turn": arguments.turn,
        "mirror": arguments.mirror,
        "head_rate": arguments.head_rate,
    }
    others = None
    if arguments.others:
        foreign = json.loads(arguments.others.read_text())
        others = (
            [str(arguments.others.parent / row["path"]) for row in foreign],
            [row["identity"] for row in foreign],
        )
        settings["others"] = f"{arguments.others.name}:{len(foreign)}"
    if arguments.start:
        settings["start"] = str(arguments.start)
    if arguments.anchor:
        settings["anchor"] = True
    results = []
    for split in arguments.split:
        for unknown in chosen:
            result = run(
                rows, arguments.manifest.parent, split, unknown, settings, arguments.cache, others
            )
            results.append(result)
            print(json.dumps(result), flush=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
