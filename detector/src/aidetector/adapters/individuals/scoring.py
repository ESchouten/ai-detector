"""Compare sightings with named individuals and set the naming threshold.

A sighting is the L2-normalised embeddings of one track's pictures. Before
comparing, every picture is adapted to the installation from its own named
sightings (see `Adaptation`). An individual's score is the mean of her k most
similar named pictures, averaged over the sighting's pictures, less a share of
the runner-up's score, so a sighting that resembles two individuals is named
less readily. Sightings seen together are decided together: one individual is
never in two places at once.

A coat check adds to the similarity of the few names a sighting resembles most:
the details its pictures share with her saved pictures, counted by the caller.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

Vectors = NDArray[np.float32]
NEAREST = 2
MARGIN = 0.75
# The share of names the threshold check withholds as strangers. With a quarter
# the adapted gallery named unknown individuals two to three times as often.
STRANGERS = 0.4
FOLDS = 5
# How far the adaptation damps the directions an individual varies in; lower
# damps harder. The enrolment study found 0.3 halved wrong names on a walkway.
DAMPING = 0.3
# A coat check compares a sighting with the SHORTLIST names most like it, with
# COAT_PICTURES saved pictures of each; COAT_FULL shared details or more add
# COAT_WEIGHT to a similarity.
SHORTLIST = 3
COAT_PICTURES = 3
COAT_FULL = 100
COAT_WEIGHT = 0.2
# A saved picture: its sighting's ID and its place among the sighting's pictures.
Picture = tuple[str, int]


@dataclass(frozen=True)
class NamedSighting:
    id: str
    name: str
    # The day the pictures were taken; the threshold check asks each day in turn.
    session: str
    vectors: Vectors
    # Later pictures of the same track, which show her from more sides. They
    # are only ever compared against: a sighting asks with `vectors` alone, as
    # new tracks do.
    later: Vectors | None = None
    # False when a person only said Yes to the detector's guess. Those are the
    # sightings it finds easy, so they are compared against like any other,
    # but the threshold check never asks with them.
    asks: bool = True

    @property
    def known(self) -> Vectors:
        if self.later is None or not len(self.later):
            return self.vectors
        return np.concatenate([self.vectors, self.later])


@dataclass(frozen=True)
class Adaptation:
    """The embedding adapted to one installation, learnt from its sightings.

    Every picture from one place shares its look: floor, light and camera
    angle. The mean sighting is taken off every picture, so that shared look
    no longer makes all individuals seem alike, and the directions in
    which one individual's sightings differ from one occasion to the next are
    damped, so what is left says more about who she is. Along a direction with
    variance v the picture is scaled by sqrt(f / (v + f)), with f `DAMPING`
    times the mean variance, and then back to unit length. Nothing is retrained.
    """

    centre: NDArray[np.float64]
    directions: NDArray[np.float64]
    factors: NDArray[np.float64]

    @classmethod
    def of(
        cls, sightings: Sequence[NamedSighting], centre: NDArray[np.floating]
    ) -> Adaptation | None:
        """Learnt from the named sightings around `centre`, the mean sighting.
        None until an individual is named on two occasions that differ, the
        least there is to learn from."""
        means = np.stack(
            [sighting.vectors.mean(axis=0, dtype=np.float64) for sighting in sightings]
        )
        rows: defaultdict[str, list[int]] = defaultdict(list)
        for row, sighting in enumerate(sightings):
            rows[sighting.name].append(row)
        parts = [
            means[own] - means[own].mean(axis=0)
            for own in rows.values()
            if len(own) > 1
        ]
        if not parts:
            return None
        deviations = np.concatenate(parts)
        _, values, axes = np.linalg.svd(deviations, full_matrices=False)
        variance = values**2 / len(deviations)
        kept = variance > variance.max() * 1e-10
        if not kept.any():
            return None
        floor = DAMPING * variance[kept].mean()
        return cls(
            np.asarray(centre, np.float64),
            axes[kept].T,
            np.sqrt(floor / (variance[kept] + floor)) - 1,
        )

    def __call__(self, vectors: Vectors) -> Vectors:
        moved = vectors - self.centre
        moved += ((moved @ self.directions) * self.factors) @ self.directions.T
        return (moved / np.linalg.norm(moved, axis=1, keepdims=True)).astype(np.float32)


@dataclass(frozen=True)
class Gallery:
    """The adapted pictures of named individuals, with the index of each
    picture's name."""

    names: tuple[str, ...]
    vectors: Vectors
    owners: NDArray[np.intp]
    # The saved pictures, and which of the vectors each one is. Later pictures
    # are kept as vectors only.
    pictures: tuple[Picture, ...] = ()
    saved: NDArray[np.intp] = field(default_factory=lambda: np.empty(0, np.intp))
    adaptation: Adaptation | None = None

    @classmethod
    def of(
        cls,
        sightings: Sequence[NamedSighting],
        centre: NDArray[np.floating] | None = None,
    ) -> Gallery:
        """`centre` is the mean of every sighting the installation has, named
        or not; without it, the named sightings' mean."""
        names = tuple(sorted({sighting.name for sighting in sightings}))
        index = {name: position for position, name in enumerate(names)}
        if not sightings:
            return cls(names, np.empty((0, 0), np.float32), np.empty(0, np.intp))
        starts = np.cumsum([0, *(len(sighting.known) for sighting in sightings)])
        vectors = np.concatenate([sighting.known for sighting in sightings])
        if centre is None:
            centre = _centre(sightings)
        adaptation = Adaptation.of(sightings, centre)
        return cls(
            names,
            vectors if adaptation is None else adaptation(vectors),
            np.concatenate(
                [
                    np.full(len(sighting.known), index[sighting.name], np.intp)
                    for sighting in sightings
                ]
            ),
            tuple(
                (sighting.id, place)
                for sighting in sightings
                for place in range(len(sighting.vectors))
            ),
            np.concatenate(
                [
                    start + np.arange(len(sighting.vectors))
                    for start, sighting in zip(starts, sightings, strict=False)
                ]
            ),
            adaptation,
        )

    def _adapted(self, vectors: Vectors) -> Vectors:
        return vectors if self.adaptation is None else self.adaptation(vectors)

    def scores(self, vectors: Vectors) -> NDArray[np.float32]:
        """One sighting's score per name, in the order of `names`."""
        return runner_up_margin(self.similarities(vectors))

    def similarities(self, vectors: Vectors) -> NDArray[np.float32]:
        """One sighting's score per name before the runner-up's share is taken off."""
        similarity = self._adapted(vectors) @ self.vectors.T
        scores = np.empty(len(self.names), np.float32)
        for owner in range(len(self.names)):
            own = similarity[:, self.owners == owner]
            nearest = min(NEAREST, own.shape[1])
            scores[owner] = (
                np.partition(own, own.shape[1] - nearest, axis=1)[:, -nearest:]
                .mean(axis=1)
                .mean()
            )
        return scores

    def shortlist(
        self, vectors: Vectors, similarities: NDArray[np.float32]
    ) -> dict[int, list[Picture]]:
        """What a coat check compares a sighting with: the names most like it,
        each with her saved pictures most like it."""
        likeness = self.vectors[self.saved] @ self._adapted(vectors).mean(axis=0)
        chosen = {}
        for owner in np.argsort(-similarities, kind="stable")[:SHORTLIST]:
            own = np.flatnonzero(self.owners[self.saved] == owner)
            nearest = own[np.argsort(-likeness[own], kind="stable")[:COAT_PICTURES]]
            chosen[int(owner)] = [self.pictures[place] for place in nearest]
        return chosen


def _centre(sightings: Sequence[NamedSighting]) -> NDArray[np.floating]:
    """The mean sighting of the named ones."""
    return np.mean([sighting.vectors.mean(axis=0) for sighting in sightings], axis=0)


def with_coat(
    similarities: NDArray[np.float32], shared: Mapping[int, int]
) -> NDArray[np.float32]:
    """Similarities with the coat details each shortlisted name shares added."""
    fused = similarities.copy()
    for owner, details in shared.items():
        fused[owner] += COAT_WEIGHT * min(details, COAT_FULL) / COAT_FULL
    return fused


def runner_up_margin(similarities: NDArray[np.float32]) -> NDArray[np.float32]:
    """Each score less a share of the best other one."""
    if len(similarities) < 2:
        return similarities
    best = similarities.max()
    second = np.partition(similarities, -2)[-2]
    return similarities - MARGIN * np.where(similarities >= best, second, best)


@dataclass(frozen=True)
class Decision:
    """A sighting's score per name, minus infinity for names out of the
    running, and whether the best is recognised."""

    scores: NDArray[np.float32]
    recognised: bool


def decide_together(
    similarities: Sequence[NDArray[np.float32]],
    beside: Sequence[Collection[int]],
    given: Sequence[int | None],
    threshold: float | None,
) -> list[Decision]:
    """Which of the sightings seen together are recognised, and as whom.

    `beside` lists, per sighting, the others seen in the same picture, and
    `given` the name a person gave it, if any. Given names stand and are
    decided first; then the surest sightings. A name recognised for one is out
    of the running for those beside it, also as their runner-up.
    """
    taken: list[set[int]] = [set() for _ in similarities]
    order = sorted(
        range(len(similarities)),
        key=lambda i: (given[i] is None, -runner_up_margin(similarities[i]).max()),
    )
    decisions: dict[int, Decision] = {}
    for sighting in order:
        row = similarities[sighting]
        best = given[sighting]
        if best is None:
            running = np.ones(len(row), bool)
            running[list(taken[sighting])] = False
            scores = np.full(len(row), -np.inf, np.float32)
            scores[running] = runner_up_margin(row[running])
            best = int(scores.argmax())
            recognised = (
                threshold is not None
                and bool(running[best])
                and bool(scores[best] >= threshold)
            )
        else:
            scores, recognised = runner_up_margin(row), True
        decisions[sighting] = Decision(scores, recognised)
        if recognised:
            for other in beside[sighting]:
                taken[other].add(best)
    return [decisions[sighting] for sighting in range(len(similarities))]


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


def by_embedding(sighting: NamedSighting, known: Gallery) -> NDArray[np.float32]:
    return known.similarities(sighting.vectors)


def self_set_threshold(
    sightings: Sequence[NamedSighting],
    precision: float,
    seed: int = 1,
    compare: Callable[[NamedSighting, Gallery], NDArray[np.float32]] = by_embedding,
) -> float | None:
    """The threshold an installation sets from its own named sightings.

    Every day's sightings are asked in turn against those of the other days,
    each time with a share of the individuals withheld as strangers, and one
    threshold is set on all answers pooled. Each such gallery adapts the
    embedding from its own names, around the mean of all named sightings;
    centring on the unnamed ones too let the check set the threshold too low
    on a small herd. `compare` gives a sighting's similarity to each name, as
    new tracks are compared. Sightings named by a Yes to the detector's guess
    are only asked against: asking with them, its easy cases, set the threshold
    too low. None until two days have names, or when no threshold reaches the
    precision.
    """
    sessions = sorted({sighting.session for sighting in sightings})
    if len(sessions) < 2:
        return None
    centre = _centre(sightings)
    rng = np.random.default_rng(seed)
    best: list[float] = []
    correct: list[bool] = []
    for session in sessions:
        queries = [
            sighting
            for sighting in sightings
            if sighting.session == session and sighting.asks
        ]
        gallery = [sighting for sighting in sightings if sighting.session != session]
        candidates = sorted(
            {query.name for query in queries} & {known.name for known in gallery}
        )
        count = round(STRANGERS * len(candidates))
        if len(candidates) > 1:
            # Three names stay where they can: scores against fewer names run
            # higher, and would set a threshold the whole herd never reaches.
            count = min(max(1, count), max(1, len(candidates) - 3))
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
                [sighting for sighting in gallery if sighting.name not in strangers],
                centre,
            )
            for query in queries:
                scores = runner_up_margin(compare(query, known))
                top = int(scores.argmax())
                best.append(float(scores[top]))
                correct.append(known.names[top] == query.name)
    return threshold_for(
        np.asarray(best, np.float32), np.asarray(correct, np.bool_), precision
    )
