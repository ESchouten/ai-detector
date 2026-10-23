"""Calibrated fusion of the embedding and the coat check, after WildFusion.

Each matcher's score for a sighting and a cow is mapped to the chance that they
are the same individual, by isotonic regression on pairs whose truth is known,
and the two chances are averaged (Čermák et al., WildFusion, 2024). That takes
the place of a coat weight picked by hand. The pairs come from other farms, so
the farm being tested never shapes its own calibration.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class Isotonic:
    """A non-decreasing map from scores to chances, fitted by pooling adjacent
    violators and interpolated between the scores it was fitted on; scores
    outside them get the nearest end's chance."""

    scores: NDArray[np.float64]
    chances: NDArray[np.float64]

    @classmethod
    def fit(cls, scores: ArrayLike, same: ArrayLike) -> Isotonic:
        x = np.asarray(scores, dtype=np.float64)
        y = np.asarray(same, dtype=np.float64)
        if not len(x):
            raise ValueError("Calibration needs pairs")
        unique, position = np.unique(x, return_inverse=True)
        totals = np.bincount(position, weights=y)
        counts = np.bincount(position).astype(np.float64)
        # Blocks of neighbouring scores, as [sum of truths, pairs, scores].
        blocks: list[list[float]] = []
        for total, count in zip(totals, counts, strict=True):
            blocks.append([total, count, 1])
            while (
                len(blocks) > 1
                and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]
            ):
                last = blocks.pop()
                blocks[-1] = [a + b for a, b in zip(blocks[-1], last, strict=True)]
        chances = np.repeat(
            [total / count for total, count, _ in blocks],
            [int(size) for _, _, size in blocks],
        )
        return cls(unique, chances)

    def __call__(self, scores: ArrayLike) -> NDArray[np.float64]:
        return np.interp(
            np.asarray(scores, dtype=np.float64), self.scores, self.chances
        )


@dataclass(frozen=True)
class Pairs:
    """Sightings with their candidate cows: the embedding's score, the coat
    matches, and whether it is the sighting's own cow."""

    deep: NDArray[np.float32]
    matches: NDArray[np.float32]
    same: NDArray[np.bool_]

    @classmethod
    def of(cls, records: Iterable[Mapping[str, Any]]) -> Pairs:
        """Pairs written by earlier runs, pooled."""
        found = list(records)
        return cls(
            np.concatenate([np.asarray(r["deep"], np.float32) for r in found]),
            np.concatenate([np.asarray(r["matches"], np.float32) for r in found]),
            np.concatenate([np.asarray(r["same"], bool) for r in found]),
        )

    def record(self) -> dict[str, list]:
        return {
            "deep": self.deep.tolist(),
            "matches": self.matches.tolist(),
            "same": self.same.tolist(),
        }


@dataclass(frozen=True)
class Calibration:
    deep: Isotonic
    coat: Isotonic
    # The farms its pairs came from.
    farms: tuple[str, ...] = ()

    @classmethod
    def fit(cls, pairs: Pairs, farms: tuple[str, ...] = ()) -> Calibration:
        return cls(
            Isotonic.fit(pairs.deep, pairs.same),
            Isotonic.fit(pairs.matches, pairs.same),
            farms,
        )

    def fuse(self, deep: ArrayLike, matches: ArrayLike) -> NDArray[np.float32]:
        """The chance of the same cow by each matcher, averaged."""
        return ((self.deep(deep) + self.coat(matches)) / 2).astype(np.float32)
