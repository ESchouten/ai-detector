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
from statistics import mean, median
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reid.adapt import Adaptation, Transform, fit
from reid.local import Matcher, coat_matches
from reid.manifest import Crop
from reid.matching import identity_scores, runner_up_margin, similarities
from reid.metrics import Decisions
from reid.splits import open_set_splits

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
    # Share of the runner-up's score taken off the best cow's before naming.
    margin: float = 0.0
    # Weights of the coat score, keypoint matches with each sighting's `top`
    # best cows by embedding; each is simulated in turn, 0 being the embedding
    # alone. The score reaches 1 at `saturation` matches.
    coats: tuple[float, ...] = (0.0,)
    top: int = 3
    query_crops: int = 3
    gallery_crops: int = 3
    saturation: float = 100.0
    # Ways to adapt the embedding to the farm from its enrolment sightings; each
    # is simulated in turn. Grouping always uses the embedding as it is, so the
    # farmer's taps stay the same.
    adapts: tuple[Adaptation, ...] = (Adaptation(),)
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


def sighting_vectors(
    vectors: NDArray[np.float32], seen: Sequence[Sequence[int]]
) -> NDArray[np.float32]:
    """One L2-normalised embedding per sighting: the mean of its crops'."""
    means = np.stack([vectors[list(indices)].mean(axis=0) for indices in seen])
    return means / np.linalg.norm(means, axis=1, keepdims=True)


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


@dataclass(frozen=True)
class _Scored:
    """Sightings scored against a gallery, per cow by embedding, with the coat
    matches of each sighting's `top` best cows.
    """

    seen: list[list[int]]
    names: NDArray[np.str_]
    deep: NDArray[np.float32]
    top: NDArray[np.intp]
    matches: NDArray[np.float32] | None

    def fused(self, weight: float, options: Options) -> NDArray[np.float32]:
        """Scores with the coat score added at `weight` and the margin taken off."""
        scores = self.deep.copy()
        if weight and self.matches is not None:
            coat = np.minimum(self.matches, options.saturation) / options.saturation
            scores[np.arange(len(scores))[:, None], self.top] += weight * coat
        return runner_up_margin(scores, options.margin)


def _score(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    gallery: Sequence[int],
    names: Sequence[str],
    queries: Sequence[int],
    matcher: Matcher | None,
    options: Options,
) -> _Scored:
    """A sighting's score for a cow is the mean of its crops' scores."""
    seen = sightings(crops, queries)
    enrolled, scores = identity_scores(
        similarities(vectors[list(queries)], vectors[list(gallery)]), names, options.k
    )
    row = {index: position for position, index in enumerate(queries)}
    deep = np.stack([scores[[row[i] for i in s]].mean(axis=0) for s in seen])
    top = np.argsort(-deep, axis=1, kind="stable")[:, : options.top]
    matches = None
    if matcher is not None and any(options.coats):
        matches = coat_matches(
            matcher,
            crops,
            vectors,
            seen,
            gallery,
            names,
            np.asarray(enrolled)[top],
            options.query_crops,
            options.gallery_crops,
        )
    return _Scored(seen, np.asarray(enrolled), deep, top, matches)


def _thresholds(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    matcher: Matcher | None,
    adaptation: Adaptation,
    options: Options,
) -> dict[float, float | None]:
    """Per coat weight, the threshold an install sets from its own named gallery.

    The gallery is split again by time with some of its cows withheld, as the
    benchmark does with a whole manifest, and each fold's sightings are scored
    the way later days will be. The threshold is the median over the folds.
    Each fold learns the adaptation again from the names of its own gallery
    only, so the check never learns from the sightings it checks.
    """
    try:
        inner = open_set_splits(
            crops, options.strangers, options.folds, options.seed + 1
        )
    except ValueError:
        return dict.fromkeys(options.coats)
    seen = sightings(crops, range(len(crops)))
    found: dict[float, list[float]] = {weight: [] for weight in options.coats}
    for split in inner:
        known = set(split.gallery)
        named = [crops[s[0]].identity if s[0] in known else "" for s in seen]
        scored = _score(
            crops,
            fit(adaptation, vectors, seen, named)(vectors),
            split.gallery,
            [crops[i].identity for i in split.gallery],
            split.queries,
            matcher,
            options,
        )
        truth = [crops[s[0]].identity for s in scored.seen]
        for weight in options.coats:
            decisions = Decisions.of(
                tuple(scored.names), scored.fused(weight, options), truth
            )
            threshold = decisions.threshold_for(options.precision)
            if threshold is not None:
                found[weight].append(threshold)
    return {
        weight: median(values) if values else None for weight, values in found.items()
    }


def _days(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    gallery: Sequence[int],
    names: Sequence[str],
    queries: Sequence[int],
    matcher: Matcher | None,
    adaptation: Adaptation,
    transform: Transform,
    options: Options,
) -> list[dict[str, Any]]:
    """Per coat weight, each later day's sightings named against the gallery at
    the install's own threshold.

    `transform` is the adaptation as learnt from every enrolment sighting.
    """
    level = "track" if any(crops[i].track for i in queries) else "crop"
    thresholds = _thresholds(
        [
            replace(crops[i], identity=name)
            for i, name in zip(gallery, names, strict=True)
        ],
        vectors[list(gallery)],
        matcher,
        adaptation,
        options,
    )
    scored = _score(
        crops, transform(vectors), gallery, names, queries, matcher, options
    )
    sessions = np.array([crops[s[0]].session for s in scored.seen])
    cows = np.array([crops[s[0]].identity for s in scored.seen])
    in_gallery = np.isin(cows, scored.names)
    results = []
    for weight in options.coats:
        fused = scored.fused(weight, options)
        ranked = scored.names[np.argsort(-fused, axis=1, kind="stable")[:, :3]]
        threshold = thresholds[weight]
        named = (
            fused.max(axis=1) >= threshold
            if threshold is not None
            else np.zeros(len(cows), dtype=bool)
        )
        right = named & (ranked[:, 0] == cows)
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
        results.append(
            {
                "coat": weight,
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
        )
    return results


def simulate(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    options: Options,
    matcher: Matcher | None = None,
) -> dict[str, Any]:
    """Enrol on the first sessions at each grouping similarity; test on the rest.

    A gallery named from the true labels is scored too, as the ceiling that
    perfect naming would give. Every gallery is scored with each adaptation and
    at each coat weight.
    """
    sessions = sorted({crop.session for crop in crops})
    if "" in sessions or len(sessions) <= options.enrol_sessions:
        raise ValueError(
            f"Enrolment needs sessions on every crop and more than "
            f"{options.enrol_sessions} of them"
        )
    if any(options.coats) and matcher is None:
        raise ValueError("A coat weight above 0 needs a matcher")
    period = set(sessions[: options.enrol_sessions])
    enrol = [i for i, crop in enumerate(crops) if crop.session in period]
    later = [i for i, crop in enumerate(crops) if crop.session not in period]
    seen = sightings(crops, enrol)
    cows = [Counter(crops[i].identity for i in s).most_common(1)[0][0] for s in seen]
    sizes = [len(s) for s in seen]
    means = sighting_vectors(vectors, seen)
    merges = merge_tree(similarities(means, means))

    def scored(named: Sequence[str]) -> list[dict[str, Any]]:
        """Every adaptation and coat weight, with `named` the name of each
        enrolment sighting, empty where it was left unnamed.
        """
        gallery = [i for s, name in zip(seen, named, strict=True) if name for i in s]
        names = [name for s, name in zip(seen, named, strict=True) if name for _ in s]
        results = []
        for adaptation in options.adapts:
            transform = fit(adaptation, vectors, seen, named)
            results.extend(
                {"adapt": str(adaptation), **entry}
                for entry in _days(
                    crops,
                    vectors,
                    gallery,
                    names,
                    later,
                    matcher,
                    adaptation,
                    transform,
                    options,
                )
            )
        return results

    labelled = scored(cows)
    grouped = []
    for merge in options.merges:
        enrolment = play_farmer(
            cut(merges, len(seen), merge).tolist(), cows, sizes, options.goal
        )
        farmer = {
            "merge": merge,
            "groups": enrolment.groups,
            "purity": enrolment.purity,
            "taps": enrolment.taps,
            "milestones": {
                str(share): taps for share, taps in enrolment.milestones.items()
            },
            # Share of the named gallery's pictures named after their own cow.
            "gallery_right": float(
                np.mean(
                    [
                        crops[i].identity == name
                        for s, name in zip(seen, enrolment.names, strict=True)
                        if name
                        for i in s
                    ]
                )
            ),
        }
        grouped.extend({**farmer, **entry} for entry in scored(enrolment.names))
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
            "margin": options.margin,
            "coats": list(options.coats),
            "top": options.top,
            "query_crops": options.query_crops,
            "gallery_crops": options.gallery_crops,
            "saturation": options.saturation,
            "matcher": matcher.name if matcher is not None else None,
            "adapts": [str(adaptation) for adaptation in options.adapts],
        },
        "labelled": labelled,
        "grouped": grouped,
    }
