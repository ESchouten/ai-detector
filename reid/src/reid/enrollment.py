"""Enrol a herd the way a farm would, then name later sightings against it.

Nothing on a user's farm is labelled. The first days' sightings are grouped by
look, the farmer names the biggest groups, and that becomes the gallery. The
labels a dataset carries are used only to play the farmer, who names each group
after the cow most of it shows, and to score what happens on later days.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import product
from statistics import mean, median
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reid.adapt import Adaptation, Transform, fit
from reid.calibration import Calibration, Pairs
from reid.local import Matcher, coat_matches
from reid.manifest import Crop
from reid.matching import identity_scores, runner_up_margin, similarities
from reid.metrics import Decisions
from reid.splits import open_set_splits, rotating_splits

MILESTONES = (0.5, 0.8, 0.9, 1.0)
# The coat variant mixing the embedding and the coat check by `Options.calibration`.
CALIBRATED = "calibrated"


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
    # Mix the embedding and the coat check by their chances of the same cow,
    # fitted on other farms, as one more coat variant (`CALIBRATED`).
    calibration: Calibration | None = None
    # Ways to adapt the embedding to the farm from its enrolment sightings; each
    # is simulated in turn. Grouping always uses the embedding as it is, so the
    # farmer's taps stay the same.
    adapts: tuple[Adaptation, ...] = (Adaptation(),)
    # How the install checks its threshold on its named gallery: `split` asks
    # the later half against the earlier and takes the median of the folds'
    # thresholds; `rotate` asks every session against the others and sets one
    # threshold on all the answers pooled.
    check: str = "split"
    # Name sightings in view at the same time together, so that a name goes to
    # at most one of them; each is simulated in turn. `times` finds a crop's
    # `clip` and `frame` in its path, as named groups of a regular expression.
    jointly: tuple[bool, ...] = (False,)
    times: str = ""
    # Let the groups the farmer left unnamed compete as anonymous cows, so a
    # sighting most like one of them stays unnamed; each is simulated in turn.
    anonymous: tuple[bool, ...] = (False,)
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


def together(
    crops: Sequence[Crop], seen: Sequence[Sequence[int]], times: str
) -> list[set[int]]:
    """For each sighting, the others in view at the same time: in the same clip
    of the same session, with overlapping frames.

    `times` finds a crop's `clip` and `frame` in its path; a sighting with a
    crop it doesn't match is in view with none.
    """
    pattern = re.compile(times)
    spans: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
    for sighting, indices in enumerate(seen):
        found = [pattern.search(crops[i].path.as_posix()) for i in indices]
        matches = [match for match in found if match is not None]
        if len(matches) < len(indices):
            continue
        frames = [int(match["frame"]) for match in matches]
        clip = (crops[indices[0]].session, matches[0]["clip"])
        spans.setdefault(clip, []).append((min(frames), max(frames), sighting))
    others: list[set[int]] = [set() for _ in seen]
    for span in spans.values():
        for position, (start, end, sighting) in enumerate(span):
            for other_start, other_end, other in span[position + 1 :]:
                if start <= other_end and other_start <= end:
                    others[sighting].add(other)
                    others[other].add(sighting)
    return others


def named_jointly(
    scores: NDArray[np.float32],
    real: NDArray[np.bool_],
    threshold: float | None,
    margin: float,
    others: Sequence[set[int]],
) -> NDArray[np.intp]:
    """The name each sighting gets, -1 for none; none at all without a threshold.

    The surest sightings are named first, and a name given to one is out of
    the running for those in view at the same time (`others`), also as their
    runner-up. Without others in view this is naming each sighting alone.
    `scores` are before the runner-up margin; only `real` names are given, the
    others are anonymous cows that compete.
    """
    given = np.full(len(scores), -1)
    if threshold is None:
        return given
    floor = scores.min()
    taken = np.zeros(scores.shape, dtype=bool)
    order = np.argsort(-runner_up_margin(scores, margin).max(axis=1), kind="stable")
    for sighting in order:
        row = np.where(taken[sighting], floor, scores[sighting])
        row = runner_up_margin(row[None], margin)[0]
        best = int(np.argmax(row))
        if row[best] >= threshold and real[best]:
            given[sighting] = best
            for other in others[sighting]:
                taken[other, best] = True
    return given


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

    def coated(self, variant: float | str, options: Options) -> NDArray[np.float32]:
        """Scores with the coat score added at a weight, or mixed with the
        embedding's by the calibration (`CALIBRATED`); cows not re-checked
        count as having no coat matches."""
        rows = np.arange(len(self.deep))[:, None]
        if variant == CALIBRATED:
            if options.calibration is None or self.matches is None:
                raise ValueError("The calibrated mix needs a calibration and matches")
            matches = np.zeros_like(self.deep)
            matches[rows, self.top] = self.matches
            return options.calibration.fuse(self.deep, matches)
        scores = self.deep.copy()
        if variant and self.matches is not None:
            coat = np.minimum(self.matches, options.saturation) / options.saturation
            scores[rows, self.top] += float(variant) * coat
        return scores

    def fused(self, variant: float | str, options: Options) -> NDArray[np.float32]:
        """Scores of a coat variant with the margin taken off."""
        return runner_up_margin(self.coated(variant, options), options.margin)

    def pairs(self, cows: NDArray[np.str_]) -> Pairs:
        """Each sighting with its re-checked cows, `cows` being its own."""
        if self.matches is None:
            raise ValueError("Pairs need coat matches")
        rows = np.arange(len(self.deep))[:, None]
        return Pairs(
            self.deep[rows, self.top].ravel(),
            self.matches.ravel(),
            (self.names[self.top] == cows[:, None]).ravel(),
        )


def _variants(options: Options) -> tuple[float | str, ...]:
    """The coat weights, and the calibrated mix when there is a calibration."""
    return options.coats + ((CALIBRATED,) if options.calibration else ())


def _rechecks(options: Options) -> bool:
    return any(options.coats) or options.calibration is not None


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
    if matcher is not None and _rechecks(options):
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
) -> dict[float | str, float | None]:
    """Per coat variant, the threshold an install sets from its own named gallery.

    The gallery is split again by time with some of its cows withheld, as the
    benchmark does with a whole manifest, and each fold's sightings are scored
    the way later days will be (see `Options.check`). Each fold learns the
    adaptation again from the names of its own gallery only, so the check never
    learns from the sightings it checks.
    """
    try:
        if options.check == "rotate":
            checks = rotating_splits(
                crops, options.strangers, options.folds, options.seed + 1
            )
        else:
            checks = open_set_splits(
                crops, options.strangers, options.folds, options.seed + 1
            )
    except ValueError:
        return dict.fromkeys(_variants(options))
    seen = sightings(crops, range(len(crops)))
    decided: dict[float | str, list[Decisions]] = {
        variant: [] for variant in _variants(options)
    }
    for split in checks:
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
        for variant in decided:
            decided[variant].append(
                Decisions.of(tuple(scored.names), scored.fused(variant, options), truth)
            )
    found: dict[float | str, float | None] = {}
    for variant, decisions in decided.items():
        if options.check == "rotate":
            found[variant] = Decisions(
                np.concatenate([d.best_scores for d in decisions]),
                np.concatenate([d.correct for d in decisions]),
                np.concatenate([d.known for d in decisions]),
            ).threshold_for(options.precision)
        else:
            each = [d.threshold_for(options.precision) for d in decisions]
            kept = [threshold for threshold in each if threshold is not None]
            found[variant] = median(kept) if kept else None
    return found


def _anonymous(name: str) -> bool:
    """An unnamed group of enrolment sightings, competing as a cow of its own."""
    return name.startswith("\0")


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
    """Per coat variant and way of naming, each later day's sightings named
    against the gallery at the install's own threshold.

    `transform` is the adaptation as learnt from every enrolment sighting.
    Anonymous cows in the gallery (see `_anonymous`) compete for sightings but
    are never given, and the install checks its threshold without them.
    """
    level = "track" if any(crops[i].track for i in queries) else "crop"
    checked = [
        (i, name)
        for i, name in zip(gallery, names, strict=True)
        if not _anonymous(name)
    ]
    thresholds = _thresholds(
        [replace(crops[i], identity=name) for i, name in checked],
        vectors[[i for i, _ in checked]],
        matcher,
        adaptation,
        options,
    )
    scored = _score(
        crops, transform(vectors), gallery, names, queries, matcher, options
    )
    sessions = np.array([crops[s[0]].session for s in scored.seen])
    cows = np.array([crops[s[0]].identity for s in scored.seen])
    real = np.array([not _anonymous(name) for name in scored.names])
    in_gallery = np.isin(cows, scored.names[real])
    alone: list[set[int]] = [set() for _ in scored.seen]
    others = together(crops, scored.seen, options.times) if options.times else alone
    results = []
    for variant, jointly in product(_variants(options), options.jointly):
        coated = scored.coated(variant, options)
        ranks = np.argsort(-np.where(real, coated, -np.inf), axis=1, kind="stable")
        ranked = scored.names[ranks[:, :3]]
        threshold = thresholds[variant]
        given = named_jointly(
            coated, real, threshold, options.margin, others if jointly else alone
        )
        apart = named_jointly(coated, real, threshold, options.margin, alone)
        named = given >= 0
        right = named & (scored.names[given] == cows)
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
                "coat": variant,
                "jointly": jointly,
                # Sightings named otherwise than each on its own would be.
                "changed": int((given != apart).sum()),
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


def _labelled_pairs(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    seen: Sequence[Sequence[int]],
    cows: Sequence[str],
    later: Sequence[int],
    matcher: Matcher | None,
    options: Options,
) -> dict[str, list] | None:
    """The later sightings with their re-checked cows of the labelled gallery,
    for calibrating the runs on other farms; none without re-checks."""
    if matcher is None or not _rechecks(options):
        return None
    gallery = [i for s in seen for i in s]
    names = [cow for s, cow in zip(seen, cows, strict=True) for _ in s]
    found = _score(crops, vectors, gallery, names, later, matcher, options)
    return found.pairs(np.array([crops[s[0]].identity for s in found.seen])).record()


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
    if _rechecks(options) and matcher is None:
        raise ValueError("A coat weight above 0 or a calibration needs a matcher")
    if options.check not in ("split", "rotate"):
        raise ValueError(f"Unknown threshold check {options.check!r}")
    if any(options.jointly) and not options.times:
        raise ValueError("Naming jointly needs the times pattern")
    period = set(sessions[: options.enrol_sessions])
    enrol = [i for i, crop in enumerate(crops) if crop.session in period]
    later = [i for i, crop in enumerate(crops) if crop.session not in period]
    seen = sightings(crops, enrol)
    cows = [Counter(crops[i].identity for i in s).most_common(1)[0][0] for s in seen]
    sizes = [len(s) for s in seen]
    means = sighting_vectors(vectors, seen)
    merges = merge_tree(similarities(means, means))

    def scored(
        named: Sequence[str], groups: Sequence[int] | None = None
    ) -> list[dict[str, Any]]:
        """Every adaptation, coat weight and way of naming, with `named` the name
        of each enrolment sighting, empty where it was left unnamed. With the
        sightings' `groups`, unnamed groups can compete as anonymous cows.
        """
        variants = [(False, named)]
        if groups is not None:
            variants = [
                (
                    anonymous,
                    [
                        name or f"\0{group}"
                        for name, group in zip(named, groups, strict=True)
                    ]
                    if anonymous
                    else named,
                )
                for anonymous in options.anonymous
            ]
        results = []
        for anonymous, competing in variants:
            gallery = [
                i for s, name in zip(seen, competing, strict=True) if name for i in s
            ]
            names = [
                name for s, name in zip(seen, competing, strict=True) if name for _ in s
            ]
            for adaptation in options.adapts:
                transform = fit(adaptation, vectors, seen, named)
                results.extend(
                    {"adapt": str(adaptation), "anonymous": anonymous, **entry}
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
    pairs = _labelled_pairs(crops, vectors, seen, cows, later, matcher, options)
    grouped = []
    for merge in options.merges:
        groups = cut(merges, len(seen), merge).tolist()
        enrolment = play_farmer(groups, cows, sizes, options.goal)
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
        grouped.extend({**farmer, **entry} for entry in scored(enrolment.names, groups))
    return {
        "crops": len(crops),
        "identities": len({crop.identity for crop in crops}),
        "enrol_sessions": sorted(period),
        "test_sessions": sorted(set(sessions) - period),
        "herd": len(set(cows)),
        "sightings": len(seen),
        "options": _record(options, matcher),
        "labelled": labelled,
        "grouped": grouped,
        "pairs": pairs,
    }


def _record(options: Options, matcher: Matcher | None) -> dict[str, Any]:
    return {
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
        "check": options.check,
        "jointly": list(options.jointly),
        "times": options.times,
        "anonymous": list(options.anonymous),
        "calibrated_on": list(options.calibration.farms)
        if options.calibration
        else None,
    }
