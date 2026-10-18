"""Closed-set ranking and open-set naming scores.

The product question is the open-set one: how many enrolled animals get a name
while wrong names, strangers included, stay rare. Rank-1 and mAP are kept to
compare with published results.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray


def rank1(
    names: Sequence[str], scores: NDArray[np.float32], truth: Sequence[str]
) -> float | None:
    """Share of enrolled queries whose best-scoring animal is their own."""
    return top_k(names, scores, truth, 1)


def top_k(
    names: Sequence[str], scores: NDArray[np.float32], truth: Sequence[str], k: int
) -> float | None:
    """Share of enrolled queries whose own animal is among the k best-scoring.

    The usable measure when a person picks the right cow from a few suggestions.
    """
    enrolled = set(names)
    known = np.array([identity in enrolled for identity in truth], dtype=bool)
    if not known.any():
        return None
    best = np.asarray(names)[np.argsort(-scores, axis=1, kind="stable")[:, :k]]
    hits = (best == np.asarray(truth)[:, None]).any(axis=1)
    return float(hits[known].mean())


def mean_average_precision(
    similarity: NDArray[np.float32],
    gallery_identities: Sequence[str],
    truth: Sequence[str],
) -> float | None:
    """Mean average precision over queries with at least one gallery picture."""
    labels = np.asarray(gallery_identities)
    precisions = []
    for row, identity in zip(similarity, truth, strict=True):
        relevant = labels[np.argsort(-row, kind="stable")] == identity
        hits = np.flatnonzero(relevant)
        if hits.size:
            precisions.append(float((np.arange(1, hits.size + 1) / (hits + 1)).mean()))
    return float(np.mean(precisions)) if precisions else None


@dataclass(frozen=True)
class Naming:
    """What a threshold does: names given, right and wrong, and strangers named."""

    threshold: float
    coverage: float | None
    precision: float
    named: int
    wrong: int
    strangers_named: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


@dataclass(frozen=True)
class Decisions:
    """For each query: the best-scoring animal, its score, and whether it is right.

    `known` marks queries whose animal is enrolled; any name for another query is
    wrong.
    """

    best_scores: NDArray[np.float32]
    correct: NDArray[np.bool_]
    known: NDArray[np.bool_]

    @classmethod
    def of(
        cls, names: Sequence[str], scores: NDArray[np.float32], truth: Sequence[str]
    ) -> Decisions:
        enrolled = set(names)
        best = np.asarray(names)[scores.argmax(axis=1)]
        known = np.array([identity in enrolled for identity in truth], dtype=bool)
        return cls(scores.max(axis=1), best == np.asarray(truth), known)

    def subset(self, mask: NDArray[np.bool_]) -> Decisions:
        return Decisions(self.best_scores[mask], self.correct[mask], self.known[mask])

    def at(self, threshold: float) -> Naming:
        named = self.best_scores >= threshold
        correct = int((named & self.correct).sum())
        count = int(named.sum())
        strangers = ~self.known
        return Naming(
            threshold,
            correct / int(self.known.sum()) if self.known.any() else None,
            correct / count if count else 1.0,
            count,
            count - correct,
            float((named & strangers).sum() / strangers.sum())
            if strangers.any()
            else None,
        )

    def threshold_for(self, precision: float) -> float | None:
        """Lowest threshold whose names are right at least `precision` of the time."""
        order = np.argsort(-self.best_scores, kind="stable")
        scores = self.best_scores[order]
        right = np.cumsum(self.correct[order])
        named = np.arange(1, len(scores) + 1)
        # A cut only exists where the score changes; equal scores are named together.
        cuts = np.append(scores[1:] < scores[:-1], True)
        good = np.flatnonzero(cuts & (right / named >= precision))
        return float(scores[good[-1]]) if good.size else None
