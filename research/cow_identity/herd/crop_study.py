"""Development study on publisher crops: can later days be named from earlier ones?

Only the ten cows that the video protocol enrols are read. Unknown animals are
simulated by leaving three of those ten out in rotation, so the three cows that
the video protocol withholds (3, 4 and 12) stay unseen by every choice made
here. Crops recorded within a day of a held-back video are never read either.
"""

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np

from ethz import development_rows
from features import cached_vectors
from openset import SCORERS, choose_limits, outcome, rates, top_two

WITHHELD = (3, 4, 12)
SPLITS = {
    # Enrolment through 27 August, as for the 28 August video.
    "early": (("20230823", "20230827"), ("20230829", "20230831")),
    # Enrolment through 31 August; queries a week later.
    "late": (("20230823", "20230831"), ("20230906", "20230910")),
}


def load(manifest, encoder, cache):
    rows = [
        row
        for row in development_rows(json.loads(Path(manifest).read_text()))
        if row["cow"] not in WITHHELD
    ]
    root = Path(manifest).parent
    return rows, cached_vectors([str(root / row["path"]) for row in rows], encoder, cache)


def calibrate(scorer, train, labels, days, classes):
    """Scores for left-out days (known) and left-out cows (unknown)."""
    known_scores, known_truth = [], []
    for day in sorted(set(days.tolist())):
        held = days == day
        if len(set(labels[~held].tolist())) < len(classes):
            continue
        known_scores.append(scorer(train[~held], labels[~held], classes, train[held]))
        known_truth.append(labels[held])
    unknown_best, unknown_margin = [], []
    for cow in classes:
        rest = [other for other in classes if other != cow]
        held = labels == cow
        _, best, margin = top_two(scorer(train[~held], labels[~held], rest, train[held]))
        unknown_best.append(best)
        unknown_margin.append(margin)
    return (
        np.concatenate(known_scores),
        np.concatenate(known_truth),
        np.concatenate(unknown_best),
        np.concatenate(unknown_margin),
    )


def study(rows, vectors, scorer_name, split, unknown, per_cow=None, seed=0):
    scorer = SCORERS[scorer_name]
    (first, last), (query_first, query_last) = SPLITS[split]
    cow = np.array([row["cow"] for row in rows])
    day = np.array([row["date"] for row in rows])
    clip = np.array([f"{row['cow']}:{row['clip']}" for row in rows])
    enrolled = ~np.isin(cow, unknown)
    training = enrolled & (day >= first) & (day <= last)
    if per_cow is not None:
        # One confirmation covers a cow's crops from one clip.
        generator = np.random.default_rng(seed)
        keep = set()
        for animal in sorted(set(cow[training].tolist())):
            clips = sorted(set(clip[training & (cow == animal)].tolist()))
            keep.update(
                generator.choice(clips, size=min(per_cow, len(clips)), replace=False)
            )
        training &= np.isin(clip, list(keep))
    query = (day >= query_first) & (day <= query_last)
    classes = sorted(set(cow[training].tolist()))
    truth = np.where(np.isin(cow[query], unknown), -1, cow[query])
    scores = scorer(vectors[training], cow[training], classes, vectors[query])
    winner, _, _ = top_two(scores)
    known = truth >= 0
    result = {
        "scorer": scorer_name,
        "split": split,
        "left_out": [int(animal) for animal in unknown],
        "confirmations_per_cow": per_cow,
        "training_crops": int(training.sum()),
        "rank1": float((np.asarray(classes)[winner][known] == truth[known]).mean()),
    }
    known_scores, known_truth, unknown_best, unknown_margin = calibrate(
        scorer, vectors[training], cow[training], day[training], classes
    )
    limits = choose_limits(
        known_scores, known_truth, classes, unknown_best, unknown_margin
    )
    result["limits"] = limits
    if limits is not None:
        counts = outcome(scores, truth, classes, limits["floor"], limits["margin"])
        result |= counts | rates(counts)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--encoder", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--scorer", nargs="+", default=sorted(SCORERS))
    parser.add_argument("--rotations", type=int, default=4)
    parser.add_argument("--per-cow", type=int, nargs="*", default=[None])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    rows, vectors = load(arguments.manifest, arguments.encoder, arguments.cache)
    cows = sorted({row["cow"] for row in rows})
    triples = list(combinations(cows, 3))
    chosen = [
        triples[i]
        for i in np.random.default_rng(0).choice(
            len(triples), size=arguments.rotations, replace=False
        )
    ]
    results = []
    for scorer in arguments.scorer:
        for split in SPLITS:
            for per_cow in arguments.per_cow:
                for unknown in chosen:
                    result = study(rows, vectors, scorer, split, unknown, per_cow)
                    result["encoder"] = arguments.encoder
                    results.append(result)
                    print(json.dumps(result), flush=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
