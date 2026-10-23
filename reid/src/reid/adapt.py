"""Adapt the embedding to one farm from its own enrolment sightings.

Every picture from one barn shares the barn's look: its floor, light and camera
angle. Each kind of adaptation first takes the farm's mean sighting off every
embedding, so that shared look no longer makes all of the farm's cows seem
alike, and then damps the directions in which pictures vary on this farm,
learnt from:

- `whiten`: all sightings, labelled or not (classic whitening);
- `tracks`: the pictures within each track, which show one cow (no labels);
- `names`: one cow's sightings on different occasions, by the farmer's names.

`named` is `names` as ai-detector does it: the centre too comes from the named
sightings only, and until a cow is named on two occasions nothing changes.

Nothing is retrained, so an install can do this in seconds on any computer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

KINDS = ("none", "center", "whiten", "tracks", "names", "named")


@dataclass(frozen=True)
class Adaptation:
    """A kind of adaptation, and how much it damps.

    Along a direction whose variance is v, the embedding is scaled by
    sqrt(f / (v + f)), with f `shrink` times the mean variance: a high `shrink`
    leaves only the centring, a low one removes those directions altogether.
    """

    kind: str = "none"
    shrink: float = 1.0

    @classmethod
    def parse(cls, text: str) -> Adaptation:
        """`kind` or `kind:shrink`, for example `names:0.3`."""
        kind, _, shrink = text.partition(":")
        if kind not in KINDS:
            raise ValueError(f"Unknown adaptation {kind!r}; use one of {KINDS}")
        return cls(kind, float(shrink) if shrink else 1.0)

    def __str__(self) -> str:
        if self.kind in ("none", "center"):
            return self.kind
        return f"{self.kind}:{self.shrink:g}"


@dataclass(frozen=True)
class Transform:
    """Centre, damp, and scale back to unit length."""

    centre: NDArray[np.float64] | None
    directions: NDArray[np.float64]
    factors: NDArray[np.float64]

    def __call__(self, vectors: NDArray[np.float32]) -> NDArray[np.float32]:
        if self.centre is None:
            return vectors
        moved = vectors - self.centre
        if len(self.factors):
            moved = (
                moved + ((moved @ self.directions) * self.factors) @ self.directions.T
            )
        return (moved / np.linalg.norm(moved, axis=1, keepdims=True)).astype(np.float32)


def _deviations(
    kind: str,
    vectors: NDArray[np.float32],
    seen: Sequence[Sequence[int]],
    names: Sequence[str],
    means: NDArray[np.float64],
) -> list[NDArray[np.float64]]:
    """How pictures vary on this farm, in the way `kind` learns it."""
    if kind == "whiten":
        return [means - means.mean(axis=0)]
    parts = []
    if kind == "tracks":
        for sighting in seen:
            if len(sighting) > 1:
                pictures = vectors[list(sighting)].astype(np.float64)
                parts.append(pictures - pictures.mean(axis=0))
    elif kind in ("names", "named"):
        by_name: dict[str, list[int]] = {}
        for sighting, name in enumerate(names):
            if name:
                by_name.setdefault(name, []).append(sighting)
        for rows in by_name.values():
            if len(rows) > 1:
                parts.append(means[rows] - means[rows].mean(axis=0))
    return parts


def fit(
    adaptation: Adaptation,
    vectors: NDArray[np.float32],
    seen: Sequence[Sequence[int]],
    names: Sequence[str] = (),
) -> Transform:
    """Learn the farm's transform from its enrolment sightings.

    `seen` holds each sighting's crops; `names` a name per sighting, empty where
    the farmer left it unnamed, and is only used by `names`.
    """
    nothing = np.zeros((vectors.shape[1], 0)), np.zeros(0)
    if adaptation.kind == "none":
        return Transform(None, *nothing)
    if adaptation.kind == "named":
        named = [i for i, name in enumerate(names) if name]
        seen, names = [seen[i] for i in named], [names[i] for i in named]
        if not seen:
            return Transform(None, *nothing)
    means = np.stack([vectors[list(s)].mean(axis=0) for s in seen]).astype(np.float64)
    centre = means.mean(axis=0)
    parts = _deviations(adaptation.kind, vectors, seen, names, means)
    if not parts:
        return Transform(None if adaptation.kind == "named" else centre, *nothing)
    deviations = np.concatenate(parts)
    _, values, axes = np.linalg.svd(deviations, full_matrices=False)
    variance = values**2 / len(deviations)
    kept = variance > variance.max() * 1e-10
    if not kept.any():
        return Transform(None if adaptation.kind == "named" else centre, *nothing)
    variance = variance[kept]
    floor = adaptation.shrink * variance.mean()
    return Transform(centre, axes[kept].T, np.sqrt(floor / (variance + floor)) - 1)
