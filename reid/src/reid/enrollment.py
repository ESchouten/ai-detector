"""Enrol a herd the way a farm would, then name later sightings against it.

Nothing on a user's farm is labelled. The first days' sightings are grouped by
look, the farmer names the biggest groups, and that becomes the gallery. The
labels a dataset carries are used only to play the farmer, who names each group
after the cow most of it shows, and to score what happens on later days.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from statistics import mean
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reid.benchmark import Options as BenchmarkOptions
from reid.benchmark import self_set_thresholds
from reid.manifest import Crop
from reid.matching import identity_scores, similarities, track_scores
from reid.splits import Split

MILESTONES = (0.5, 0.8, 0.9, 1.0)


@dataclass(frozen=True)
class Options:
    # The first sessions are the enrolment period; every later one is a test day.
    enrol_sessions: int = 2
    # Similarities at which sightings are grouped; each is simulated in turn.
    merges: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8)
    # The farmer names groups until this share of the cows seen has a name.
    goal: float = 0.9
    k: int = 2
    precision: float = 0.99
    strangers: float = 0.25
    folds: int = 3
    seed: int = 0


def sightings(crops: Sequence[Crop], indices: Sequence[int]) -> list[list[int]]:
    """Crops of one track are one sighting; a crop without a track stands alone."""
    groups: dict[str, list[int]] = {}
    for index in indices:
        crop = crops[index]
        key = f"{crop.session}\0{crop.track}" if crop.track else f"\0{index}"
        groups.setdefault(key, []).append(index)
    return list(groups.values())


def merge_tree(similarity: NDArray[np.floating]) -> list[tuple[int, int, float]]:
    """Every average-linkage merge of the items, with the similarity it joined at.

    Found with the nearest-neighbour chain, which updates one row per merge
    instead of searching all pairs. A merge joins the groups its two items
    represent; the first item goes on representing the joined group.
    """
    count = len(similarity)
    linked = np.array(similarity, dtype=np.float64)
    np.fill_diagonal(linked, -np.inf)
    sizes = np.ones(count)
    merges: list[tuple[int, int, float]] = []
    chain: list[int] = []
    while len(merges) < count - 1:
        if not chain:
            chain.append(int(np.flatnonzero(sizes)[0]))
        last = chain[-1]
        row = linked[last]
        nearest = int(np.argmax(row))
        # On a tie, going back down the chain keeps it from cycling.
        if len(chain) > 1 and row[chain[-2]] >= row[nearest]:
            nearest = chain[-2]
        if len(chain) == 1 or nearest != chain[-2]:
            chain.append(nearest)
            continue
        del chain[-2:]
        merges.append((last, nearest, float(row[nearest])))
        joined = (sizes[last] * row + sizes[nearest] * linked[nearest]) / (
            sizes[last] + sizes[nearest]
        )
        linked[last], linked[:, last] = joined, joined
        linked[nearest], linked[:, nearest] = -np.inf, -np.inf
        linked[last, last] = -np.inf
        sizes[last] += sizes[nearest]
        sizes[nearest] = 0
    return merges


def cut(
    merges: Sequence[tuple[int, int, float]], count: int, threshold: float
) -> NDArray[np.intp]:
    """Group number of each item once every merge at or above `threshold` is made.

    Average linkage never joins two groups more readily than it joined their
    parts, so this is the tree cut at that similarity.
    """
    parent = list(range(count))

    def root(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first, second, similarity in merges:
        if similarity >= threshold:
            parent[root(second)] = root(first)
    return np.unique([root(item) for item in range(count)], return_inverse=True)[1]


@dataclass(frozen=True)
class Enrolment:
    """What the farmer did with the groups.

    `names` holds a name per sighting, empty where its group was left unnamed.
    `purity` is the share of sightings whose group most shows their own cow.
    `milestones` gives the taps after which each share of the cows had a name,
    None when naming every group never got there.
    """

    names: tuple[str, ...]
    groups: int
    taps: int
    milestones: dict[float, int | None]
    purity: float


def play_farmer(
    groups: Sequence[int], cows: Sequence[str], sizes: Sequence[int], goal: float
) -> Enrolment:
    """Name groups with the most sightings first, one tap each, until `goal` of
    the cows seen have a name.

    Each group is named after the cow most of its pictures show, as a farmer
    looking at it would, so the rest of a mixed group gets a wrong name.
    """
    members: dict[int, list[int]] = {}
    for sighting, group in enumerate(groups):
        members.setdefault(int(group), []).append(sighting)
    majority = {}
    for group, sightings_ in members.items():
        weights: Counter[str] = Counter()
        for sighting in sightings_:
            weights[cows[sighting]] += sizes[sighting]
        majority[group] = weights.most_common(1)[0][0]
    order = sorted(
        members,
        key=lambda group: (
            -len(members[group]),
            -sum(sizes[sighting] for sighting in members[group]),
            group,
        ),
    )
    herd = set(cows)
    known: set[str] = set()
    named: dict[int, str] = {}
    milestones: dict[float, int | None] = dict.fromkeys(MILESTONES)
    taps = None
    for tap, group in enumerate(order, start=1):
        if taps is None:
            named[group] = majority[group]
        known.add(majority[group])
        share = len(known) / len(herd)
        for milestone in MILESTONES:
            if milestones[milestone] is None and share >= milestone:
                milestones[milestone] = tap
        if taps is None and share >= goal:
            taps = tap
    pure = sum(
        majority[int(group)] == cow for group, cow in zip(groups, cows, strict=True)
    )
    return Enrolment(
        tuple(named.get(int(group), "") for group in groups),
        len(members),
        len(order) if taps is None else taps,
        milestones,
        pure / len(cows),
    )


def _threshold(
    crops: Sequence[Crop], vectors: NDArray[np.float32], level: str, options: Options
) -> float | None:
    """The threshold an install sets from its own named gallery."""
    whole = Split("enrolled", tuple(range(len(crops))), (), frozenset(), True)
    found = self_set_thresholds(
        crops,
        vectors,
        [whole],
        BenchmarkOptions(
            strangers=options.strangers,
            folds=options.folds,
            seed=options.seed,
            k=options.k,
            precision=options.precision,
        ),
    )
    return found[0].get(level)


def _days(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    gallery: Sequence[int],
    names: Sequence[str],
    queries: Sequence[int],
    options: Options,
) -> dict[str, Any]:
    """Each later day's sightings named against the gallery at its own threshold."""
    level = "track" if any(crops[i].track for i in queries) else "crop"
    threshold = _threshold(
        [
            replace(crops[i], identity=name)
            for i, name in zip(gallery, names, strict=True)
        ],
        vectors[list(gallery)],
        level,
        options,
    )
    enrolled, scores = identity_scores(
        similarities(vectors[list(queries)], vectors[list(gallery)]), names, options.k
    )
    asked = [crops[i] for i in queries]
    firsts, averaged = track_scores(
        scores,
        [f"{crop.session}\0{crop.track}" if crop.track else "" for crop in asked],
    )
    ranked = np.asarray(enrolled)[np.argsort(-averaged, axis=1, kind="stable")[:, :3]]
    sessions = np.array([asked[i].session for i in firsts])
    cows = np.array([asked[i].identity for i in firsts])
    best = ranked[:, 0]
    named = (
        averaged.max(axis=1) >= threshold
        if threshold is not None
        else np.zeros(len(firsts), dtype=bool)
    )
    right = named & (best == cows)
    in_gallery = np.isin(cows, enrolled)
    top3 = (ranked == cows[:, None]).any(axis=1)
    days: list[dict[str, Any]] = []
    for session in sorted(set(sessions)):
        day = sessions == session
        present = set(cows[day])
        days.append(
            {
                "session": session,
                "sightings": int(day.sum()),
                "named": float(named[day].mean()),
                "right": float(right[day].sum() / named[day].sum())
                if named[day].any()
                else None,
                "wrong": int((named & ~right)[day].sum()),
                "cows": len(present),
                "recognised": len(set(cows[day & right])) / len(present),
                "misnamed_cows": len(set(cows[day & named & ~right])),
                "top3": float(top3[day & in_gallery].mean())
                if (day & in_gallery).any()
                else None,
            }
        )
    rights = [day["right"] for day in days if day["right"] is not None]
    tops = [day["top3"] for day in days if day["top3"] is not None]
    return {
        "level": level,
        "threshold": threshold,
        "days": days,
        "mean": {
            "named": mean(day["named"] for day in days),
            "right": mean(rights) if rights else None,
            "recognised": mean(day["recognised"] for day in days),
            "top3": mean(tops) if tops else None,
            "wrong": sum(day["wrong"] for day in days),
        },
    }


def simulate(
    crops: Sequence[Crop], vectors: NDArray[np.float32], options: Options
) -> dict[str, Any]:
    """Enrol on the first sessions at each grouping similarity; test on the rest.

    A gallery named from the true labels is scored too, as the ceiling that
    perfect naming would give.
    """
    sessions = sorted({crop.session for crop in crops})
    if "" in sessions or len(sessions) <= options.enrol_sessions:
        raise ValueError(
            f"Enrolment needs sessions on every crop and more than "
            f"{options.enrol_sessions} of them"
        )
    period = set(sessions[: options.enrol_sessions])
    enrol = [i for i, crop in enumerate(crops) if crop.session in period]
    later = [i for i, crop in enumerate(crops) if crop.session not in period]
    seen = sightings(crops, enrol)
    cows = [Counter(crops[i].identity for i in s).most_common(1)[0][0] for s in seen]
    sizes = [len(s) for s in seen]
    means = np.stack([vectors[s].mean(axis=0) for s in seen])
    means /= np.linalg.norm(means, axis=1, keepdims=True)
    merges = merge_tree(similarities(means, means))
    labelled = _days(
        crops, vectors, enrol, [crops[i].identity for i in enrol], later, options
    )
    grouped = []
    for merge in options.merges:
        enrolment = play_farmer(
            cut(merges, len(seen), merge).tolist(), cows, sizes, options.goal
        )
        gallery = [
            i for s, name in zip(seen, enrolment.names, strict=True) if name for i in s
        ]
        names = [
            name
            for s, name in zip(seen, enrolment.names, strict=True)
            if name
            for _ in s
        ]
        grouped.append(
            {
                "merge": merge,
                "groups": enrolment.groups,
                "purity": enrolment.purity,
                "taps": enrolment.taps,
                "milestones": {
                    str(share): taps for share, taps in enrolment.milestones.items()
                },
                "gallery_right": float(
                    np.mean(
                        [
                            crops[i].identity == n
                            for i, n in zip(gallery, names, strict=True)
                        ]
                    )
                ),
                **_days(crops, vectors, gallery, names, later, options),
            }
        )
    return {
        "crops": len(crops),
        "identities": len({crop.identity for crop in crops}),
        "enrol_sessions": sorted(period),
        "test_sessions": sorted(set(sessions) - period),
        "herd": len(set(cows)),
        "sightings": len(seen),
        "options": {
            "goal": options.goal,
            "k": options.k,
            "precision": options.precision,
        },
        "labelled": labelled,
        "grouped": grouped,
    }
