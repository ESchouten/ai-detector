"""Split crops into an earlier gallery and later queries, with withheld strangers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from reid.manifest import Crop


@dataclass(frozen=True)
class Split:
    """Gallery and query indices into the crop list.

    Strangers are animals seen among the queries whose gallery crops were removed,
    so a correct answer for them is no name at all. `time_disjoint` is False when
    the crops carried no sessions and the split had to be random, which makes
    every score optimistic.
    """

    name: str
    gallery: tuple[int, ...]
    queries: tuple[int, ...]
    strangers: frozenset[str]
    time_disjoint: bool
    # The strangers' gallery crops, left out of this fold.
    withheld: tuple[int, ...] = ()


def time_split(
    crops: Sequence[Crop], gallery_fraction: float = 0.5, gap_sessions: int = 0
) -> tuple[tuple[int, ...], tuple[int, ...], bool]:
    """Earliest sessions form the gallery, later ones the queries.

    The gallery holds the shortest run of sessions with at least
    `gallery_fraction` of the crops. `gap_sessions` sessions after it are left
    out, so a cow resting in one spot across midnight is not her own query.
    """
    sessions = sorted({crop.session for crop in crops})
    if "" in sessions or len(sessions) < 2 + gap_sessions:
        return (*_random_split(crops, gallery_fraction), False)
    counts = Counter(crop.session for crop in crops)
    total = 0
    cut = len(sessions) - 1 - gap_sessions
    for index, session in enumerate(sessions[: len(sessions) - 1 - gap_sessions]):
        total += counts[session]
        if total >= gallery_fraction * len(crops):
            cut = index + 1
            break
    gallery_sessions = set(sessions[:cut])
    query_sessions = set(sessions[cut + gap_sessions :])
    return (
        tuple(i for i, crop in enumerate(crops) if crop.session in gallery_sessions),
        tuple(i for i, crop in enumerate(crops) if crop.session in query_sessions),
        True,
    )


def _random_split(
    crops: Sequence[Crop], gallery_fraction: float
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    rng = np.random.default_rng(0)
    by_identity: dict[str, list[int]] = {}
    for index, crop in enumerate(crops):
        by_identity.setdefault(crop.identity, []).append(index)
    gallery: list[int] = []
    queries: list[int] = []
    for indices in by_identity.values():
        shuffled = rng.permutation(indices).tolist()
        count = max(1, round(gallery_fraction * len(shuffled)))
        if len(shuffled) > 1:
            count = min(count, len(shuffled) - 1)
        gallery.extend(shuffled[:count])
        queries.extend(shuffled[count:])
    return tuple(sorted(gallery)), tuple(sorted(queries))


def _with_strangers(
    crops: Sequence[Crop],
    gallery: tuple[int, ...],
    queries: tuple[int, ...],
    disjoint: bool,
    strangers_fraction: float,
    folds: int,
    rng: np.random.Generator,
    prefix: str = "",
) -> list[Split]:
    """One split per fold, each withholding its own random share of the animals."""
    enrolled = {crops[i].identity for i in gallery}
    candidates = sorted({crops[i].identity for i in queries} & enrolled)
    count = round(strangers_fraction * len(candidates))
    if strangers_fraction > 0 and len(candidates) > 1:
        count = min(max(1, count), len(candidates) - 1)
    if count == 0:
        return [Split(f"{prefix}closed", gallery, queries, frozenset(), disjoint)]
    splits = []
    for fold in range(folds):
        strangers = frozenset(
            str(identity)
            for identity in rng.choice(candidates, size=count, replace=False)
        )
        splits.append(
            Split(
                f"{prefix}fold-{fold + 1}",
                tuple(i for i in gallery if crops[i].identity not in strangers),
                queries,
                strangers,
                disjoint,
                tuple(i for i in gallery if crops[i].identity in strangers),
            )
        )
    return splits


def open_set_splits(
    crops: Sequence[Crop],
    strangers_fraction: float = 0.25,
    folds: int = 3,
    seed: int = 0,
    gallery_fraction: float = 0.5,
    gap_sessions: int = 0,
) -> list[Split]:
    """One time split, with a different set of withheld animals in each fold."""
    gallery, queries, disjoint = time_split(crops, gallery_fraction, gap_sessions)
    if not gallery or not queries:
        raise ValueError("The split left no gallery or no queries")
    return _with_strangers(
        crops,
        gallery,
        queries,
        disjoint,
        strangers_fraction,
        folds,
        np.random.default_rng(seed),
    )


def rotating_splits(
    crops: Sequence[Crop],
    strangers_fraction: float = 0.25,
    folds: int = 3,
    seed: int = 0,
) -> list[Split]:
    """Every session in turn asked against all the others, each with folds of
    withheld animals.

    Every picture is asked once per fold instead of only the later half, which
    is what a farm with a few days of named sightings needs.
    """
    sessions = sorted({crop.session for crop in crops})
    if "" in sessions or len(sessions) < 2:
        raise ValueError("Rotating needs sessions on every crop and at least two")
    rng = np.random.default_rng(seed)
    splits = []
    for session in sessions:
        queries = tuple(i for i, crop in enumerate(crops) if crop.session == session)
        gallery = tuple(i for i, crop in enumerate(crops) if crop.session != session)
        splits.extend(
            _with_strangers(
                crops,
                gallery,
                queries,
                True,
                strangers_fraction,
                folds,
                rng,
                f"{session}-",
            )
        )
    return splits
