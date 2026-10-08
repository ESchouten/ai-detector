"""Naming one crop from confirmed examples, with a calibrated refusal.

Scores are one number per enrolled cow. A crop is named only when the best
score is high enough and far enough above the runner-up; the two limits are
chosen from the herd's own examples by leaving animals and days out, never from
the footage being evaluated.
"""

import numpy as np
import torch


def gallery_scores(train, labels, classes, queries):
    """Best cosine similarity to any confirmed example of each cow."""
    scores = np.empty((len(queries), len(classes)), dtype=np.float32)
    for column, cow in enumerate(classes):
        scores[:, column] = (queries @ train[labels == cow].T).max(1)
    return scores


def prototype_scores(train, labels, classes, queries):
    """Cosine similarity to the mean example of each cow."""
    means = np.stack([train[labels == cow].mean(0) for cow in classes])
    means /= np.linalg.norm(means, axis=1, keepdims=True)
    return (queries @ means.T).astype(np.float32)


def fit_linear(train, labels, classes, decay=1e-3, steps=200, seed=0):
    """Multinomial logistic regression on fixed descriptors, class-balanced."""
    torch.manual_seed(seed)
    index = {cow: i for i, cow in enumerate(classes)}
    target = torch.tensor([index[cow] for cow in labels.tolist()])
    features = torch.from_numpy(train).float()
    counts = torch.bincount(target, minlength=len(classes)).float()
    weight = (counts.sum() / (len(classes) * counts))[target]
    layer = torch.nn.Linear(features.shape[1], len(classes))
    torch.nn.init.zeros_(layer.weight)
    torch.nn.init.zeros_(layer.bias)
    optimizer = torch.optim.LBFGS(
        layer.parameters(), max_iter=steps, line_search_fn="strong_wolfe"
    )

    def closure():
        optimizer.zero_grad()
        loss = (
            torch.nn.functional.cross_entropy(layer(features), target, reduction="none")
            * weight
        ).mean() + decay * layer.weight.square().sum()
        loss.backward()
        return loss

    optimizer.step(closure)
    return layer.weight.detach().numpy(), layer.bias.detach().numpy()


def linear_scores(train, labels, classes, queries, decay=1e-3):
    weight, bias = fit_linear(train, labels, classes, decay)
    return (queries @ weight.T + bias).astype(np.float32)


SCORERS = {
    "gallery": gallery_scores,
    "prototype": prototype_scores,
    "linear": linear_scores,
}


def top_two(scores, rivals=None):
    """Winner, its score and its lead; `rivals` compete but can never be named."""
    order = np.argsort(-scores, axis=1)
    rows = np.arange(len(scores))
    best = scores[rows, order[:, 0]]
    second = scores[rows, order[:, 1]]
    if rivals is not None and rivals.shape[1]:
        second = np.maximum(second, rivals.max(1))
    return order[:, 0], best, best - second


def outcome(scores, truth, classes, floor, margin_floor):
    """Counts for one pair of limits; `truth` holds the cow or -1 when unknown."""
    winner, best, margin = top_two(scores)
    named = (best >= floor) & (margin >= margin_floor)
    predicted = np.asarray(classes)[winner]
    known = truth >= 0
    return {
        "known": int(known.sum()),
        "unknown": int((~known).sum()),
        "correct": int((named & known & (predicted == truth)).sum()),
        "wrong_known": int((named & known & (predicted != truth)).sum()),
        "named_unknown": int((named & ~known).sum()),
    }


def rates(counts):
    named = counts["correct"] + counts["wrong_known"] + counts["named_unknown"]
    return {
        "precision": counts["correct"] / named if named else None,
        "coverage": counts["correct"] / counts["known"] if counts["known"] else None,
        "unknown_named": (
            counts["named_unknown"] / counts["unknown"] if counts["unknown"] else None
        ),
    }


def choose_limits(
    known_scores,
    known_truth,
    classes,
    unknown_best,
    unknown_margin,
    min_precision=0.995,
    max_unknown=0.005,
    steps=60,
):
    """Most names on left-out known crops, within the error budget on both sides.

    `known_scores` come from examples of a day the scorer never saw;
    `unknown_best` and `unknown_margin` from animals it never saw.
    """
    winner, best, margin = top_two(known_scores)
    correct = np.asarray(classes)[winner] == known_truth
    floors = np.quantile(
        np.concatenate([best, unknown_best]), np.linspace(0, 1, steps + 1)
    )
    margins = np.quantile(
        np.concatenate([margin, unknown_margin]), np.linspace(0, 0.98, steps + 1)
    )
    chosen = None
    for floor in floors:
        for margin_floor in margins:
            named = (best >= floor) & (margin >= margin_floor)
            unknown = (unknown_best >= floor) & (unknown_margin >= margin_floor)
            good = int((named & correct).sum())
            total = int(named.sum()) + int(unknown.sum())
            if total == 0 or good / total < min_precision:
                continue
            if unknown.mean() > max_unknown:
                continue
            if chosen is None or good > chosen[0]:
                chosen = (good, float(floor), float(margin_floor))
    if chosen is None:
        return None
    return {"floor": chosen[1], "margin": chosen[2], "left_out_correct": chosen[0]}


def best_possible(
    scores, truth, classes, rivals=None, min_precision=0.99, max_unknown=0.01, steps=80
):
    """Upper bound: limits chosen on the scored crops themselves. Not a result."""
    winner, best, margin = top_two(scores, rivals)
    known = truth >= 0
    correct = known & (np.asarray(classes)[winner] == truth)
    chosen = (0, None, None)
    for floor in np.quantile(best, np.linspace(0, 1, steps + 1)):
        for margin_floor in np.quantile(margin, np.linspace(0, 0.98, steps + 1)):
            named = (best >= floor) & (margin >= max(margin_floor, 0.0))
            total = int(named.sum())
            good = int((named & correct).sum())
            if total == 0 or good / total < min_precision:
                continue
            if (~known).any() and (named & ~known).sum() / (~known).sum() > max_unknown:
                continue
            if good > chosen[0]:
                chosen = (good, float(floor), float(margin_floor))
    return {
        "coverage": chosen[0] / int(known.sum()),
        "floor": chosen[1],
        "margin": chosen[2],
    }
