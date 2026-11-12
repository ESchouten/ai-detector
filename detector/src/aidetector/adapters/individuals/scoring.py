"""Compare sightings with named individuals and set the naming threshold.

A sighting is the L2-normalised embeddings of one track's pictures. An
individual's score is the mean of her k most similar named pictures, averaged
over the sighting's pictures, less a share of the runner-up's score, so a
sighting that resembles two individuals is named less readily.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Vectors = NDArray[np.float32]
NEAREST = 2
MARGIN = 0.75
STRANGERS = 0.25
FOLDS = 3


@dataclass(frozen=True)
class NamedSighting:
    name: str
    # The day the pictures were taken; the threshold check asks each day in turn.
    session: str
    vectors: Vectors


@dataclass(frozen=True)
class Gallery:
    """The pictures of named individuals, with the index of each picture's name."""

    names: tuple[str, ...]
    vectors: Vectors
    owners: NDArray[np.intp]

    @classmethod
    def of(cls, sightings: Sequence[NamedSighting]) -> Gallery:
        names = tuple(sorted({sighting.name for sighting in sightings}))
        index = {name: position for position, name in enumerate(names)}
        if not sightings:
            return cls(names, np.empty((0, 0), np.float32), np.empty(0, np.intp))
        return cls(
            names,
            np.concatenate([sighting.vectors for sighting in sightings]),
            np.concatenate(
                [
                    np.full(len(sighting.vectors), index[sighting.name], np.intp)
                    for sighting in sightings
                ]
            ),
        )

    def scores(self, vectors: Vectors) -> NDArray[np.float32]:
        """One sighting's score per name, in the order of `names`."""
        similarity = vectors @ self.vectors.T
        scores = np.empty(len(self.names), np.float32)
        for owner in range(len(self.names)):
            own = similarity[:, self.owners == owner]
            nearest = min(NEAREST, own.shape[1])
            scores[owner] = (
                np.partition(own, own.shape[1] - nearest, axis=1)[:, -nearest:]
                .mean(axis=1)
                .mean()
            )
        if len(scores) < 2:
            return scores
        best = scores.max()
        second = np.partition(scores, -2)[-2]
        return scores - MARGIN * np.where(scores >= best, second, best)


def threshold_for(
    scores: NDArray[np.float32], correct: NDArray[np.bool_], precision: float
) -> float | None:
    """Lowest score whose names are right at least `precision` of the time."""
    order = np.argsort(-scores, kind="stable")
    ranked = scores[order]
    right = np.cumsum(correct[order])
    named = np.arange(1, len(ranked) + 1)
    # A cut only exists where the score changes; equal scores are named together.
    cuts = np.append(ranked[1:] < ranked[:-1], True)
    good = np.flatnonzero(cuts & (right / named >= precision))
    return float(ranked[good[-1]]) if good.size else None


def self_set_threshold(
    sightings: Sequence[NamedSighting], precision: float, seed: int = 1
) -> float | None:
    """The threshold an installation sets from its own named sightings.

    Every day's sightings are asked in turn against those of the other days,
    each time with a share of the individuals withheld as strangers, and one
    threshold is set on all answers pooled. None until two days have names, or
    when no threshold reaches the precision.
    """
    sessions = sorted({sighting.session for sighting in sightings})
    if len(sessions) < 2:
        return None
    rng = np.random.default_rng(seed)
    best: list[float] = []
    correct: list[bool] = []
    for session in sessions:
        queries = [sighting for sighting in sightings if sighting.session == session]
        gallery = [sighting for sighting in sightings if sighting.session != session]
        candidates = sorted(
            {query.name for query in queries} & {known.name for known in gallery}
        )
        count = round(STRANGERS * len(candidates))
        if len(candidates) > 1:
            count = min(max(1, count), len(candidates) - 1)
        withheld = (
            [frozenset[str]()]
            if count == 0
            else [
                frozenset(str(name) for name in rng.choice(candidates, count, False))
                for _ in range(FOLDS)
            ]
        )
        for strangers in withheld:
            known = Gallery.of(
                [sighting for sighting in gallery if sighting.name not in strangers]
            )
            for query in queries:
                scores = known.scores(query.vectors)
                top = int(scores.argmax())
                best.append(float(scores[top]))
                correct.append(known.names[top] == query.name)
    return threshold_for(
        np.asarray(best, np.float32), np.asarray(correct, np.bool_), precision
    )
