"""Score an embedder on a manifest: one time split, several sets of strangers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reid.backbones import Embedder
from reid.manifest import Crop
from reid.matching import identity_scores, similarities, track_scores
from reid.metrics import Decisions, mean_average_precision, top_k
from reid.splits import Split, open_set_splits

MAP_QUERIES = 4000


@dataclass(frozen=True)
class Options:
    strangers: float = 0.25
    folds: int = 3
    seed: int = 0
    k: int = 2
    gallery_fraction: float = 0.5
    gap_sessions: int = 0
    precision: float = 0.99
    max_per_identity: int | None = None


def subsample(
    crops: Sequence[Crop], max_per_identity: int | None, seed: int = 0
) -> tuple[Crop, ...]:
    """At most N crops per animal, spread over the list, for quick runs."""
    if max_per_identity is None:
        return tuple(crops)
    by_identity: dict[str, list[int]] = {}
    for index, crop in enumerate(crops):
        by_identity.setdefault(crop.identity, []).append(index)
    rng = np.random.default_rng(seed)
    kept: list[int] = []
    for indices in by_identity.values():
        if len(indices) <= max_per_identity:
            kept.extend(indices)
        else:
            kept.extend(rng.choice(indices, size=max_per_identity, replace=False))
    return tuple(crops[index] for index in sorted(kept))


def embeddings(
    crops: Sequence[Crop], embedder: Embedder, cache: Path | None = None
) -> NDArray[np.float32]:
    """Embed every crop once; cached by model name and the pictures' paths and dates."""
    if cache is None:
        return embedder.embed([crop.path for crop in crops])
    digest = hashlib.sha256(
        "\n".join(
            [
                embedder.name,
                *(f"{crop.path}\t{crop.path.stat().st_mtime_ns}" for crop in crops),
            ]
        ).encode()
    ).hexdigest()[:16]
    path = cache / f"{re.sub(r'[^\w.+-]', '_', embedder.name)}-{digest}.npy"
    if path.exists():
        return np.load(path)
    vectors = embedder.embed([crop.path for crop in crops])
    cache.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    return vectors


@dataclass(frozen=True)
class _Level:
    decisions: Decisions
    night: NDArray[np.bool_] | None
    rank1: float | None
    top3: float | None


@dataclass(frozen=True)
class _Scored:
    split: Split
    rank1: float | None
    map: float | None
    levels: dict[str, _Level]


@dataclass(frozen=True)
class _Fold:
    scored: _Scored
    oracle: dict[str, float | None]
    self_set: dict[str, float | None]


@dataclass(frozen=True)
class Scores:
    """Every fold's decisions and thresholds on one farm.

    Kept apart from the report so a threshold from other farms can be tried on
    the same decisions without matching everything again.
    """

    crops: int
    identities: int
    sessions: int
    time_disjoint: bool
    folds: list[_Fold]


@dataclass(frozen=True)
class _Matched:
    """Every query of one time split scored against every enrolled animal."""

    names: tuple[str, ...]
    scores: NDArray[np.float32]
    queries: list[Crop]
    map: float | None


def _match(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    gallery: Sequence[int],
    queries: Sequence[int],
    k: int,
    ranking: bool,
) -> _Matched:
    identities = [crops[i].identity for i in gallery]
    asked = [crops[i] for i in queries]
    similarity = similarities(vectors[list(queries)], vectors[list(gallery)])
    names, scores = identity_scores(similarity, identities, k)
    truth = [crop.identity for crop in asked]
    ranked = None
    if ranking:
        # mAP is only there to compare with papers; queries spread evenly over
        # the list estimate it closely without sorting every row.
        sample = np.unique(
            np.linspace(0, len(asked) - 1, min(len(asked), MAP_QUERIES)).astype(int)
        )
        ranked = mean_average_precision(
            similarity[sample], identities, [truth[i] for i in sample]
        )
    return _Matched(names, scores, asked, ranked)


def _levels(
    matched: _Matched,
    strangers: frozenset[str],
    absent: frozenset[str] = frozenset(),
) -> dict[str, _Level]:
    """Decisions per crop and per track.

    Strangers lose their enrolled photos but are still asked about; absent
    animals are left out altogether.
    """
    hidden = strangers | absent
    keep = [i for i, name in enumerate(matched.names) if name not in hidden]
    rows = [i for i, crop in enumerate(matched.queries) if crop.identity not in absent]
    names = tuple(matched.names[i] for i in keep)
    scores = matched.scores[np.ix_(rows, keep)]
    queries = [matched.queries[i] for i in rows]
    truth = [crop.identity for crop in queries]
    night = np.array([crop.night is True for crop in queries])
    known_light = any(crop.night is not None for crop in queries)
    levels = {
        "crop": _Level(
            Decisions.of(names, scores, truth),
            night if known_light else None,
            top_k(names, scores, truth, 1),
            top_k(names, scores, truth, 3),
        )
    }
    if any(crop.track for crop in queries):
        firsts, averaged = track_scores(scores, [crop.track for crop in queries])
        track_truth = [truth[i] for i in firsts]
        levels["track"] = _Level(
            Decisions.of(names, averaged, track_truth),
            night[list(firsts)] if known_light else None,
            top_k(names, averaged, track_truth, 1),
            top_k(names, averaged, track_truth, 3),
        )
    return levels


def _scored_folds(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    splits: Sequence[Split],
    k: int,
    ranking: bool = True,
) -> list[_Scored]:
    """Score every fold of one time split from a single match.

    Folds share their queries and differ only in whose gallery photos are
    withheld, and an animal's score depends on her own photos alone, so every
    enrolled animal is scored once and each fold drops its strangers. mAP is
    closed-set: queries against the whole gallery.
    """
    first = splits[0]
    gallery = sorted((*first.gallery, *first.withheld))
    matched = _match(crops, vectors, gallery, first.queries, k, ranking)
    scored = []
    for split in splits:
        levels = _levels(matched, split.strangers)
        rank = levels["crop"].rank1 if ranking else None
        scored.append(_Scored(split, rank, matched.map, levels))
    return scored


def self_set_thresholds(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    splits: Sequence[Split],
    options: Options,
) -> list[dict[str, float | None]]:
    """Per fold, the threshold a farm can set from its own enrolled photos alone.

    The gallery is split again by time with some of its animals withheld, as the
    benchmark does with the whole manifest, and the threshold is chosen there.
    On a farm the gallery is what the farmer named, so no label beyond it is used.
    The inner split is matched once; each fold then leaves out its own strangers,
    who are not enrolled on that farm at all.
    """
    full = sorted((*splits[0].gallery, *splits[0].withheld))
    enrolled = [crops[i] for i in full]
    try:
        inner = open_set_splits(
            enrolled,
            options.strangers,
            options.folds,
            options.seed + 1,
            options.gallery_fraction,
        )
    except ValueError:
        return [{} for _ in splits]
    matched = _match(
        enrolled,
        vectors[full],
        sorted((*inner[0].gallery, *inner[0].withheld)),
        inner[0].queries,
        options.k,
        ranking=False,
    )
    thresholds: list[dict[str, float | None]] = []
    for split in splits:
        found: dict[str, list[float]] = {}
        for inner_split in inner:
            levels = _levels(matched, inner_split.strangers, split.strangers)
            for level, scored_level in levels.items():
                threshold = scored_level.decisions.threshold_for(options.precision)
                if threshold is not None:
                    found.setdefault(level, []).append(threshold)
        thresholds.append({level: median(values) for level, values in found.items()})
    return thresholds


def score(
    crops: Sequence[Crop], vectors: NDArray[np.float32], options: Options
) -> Scores:
    """Match every fold's queries and find its thresholds."""
    splits = open_set_splits(
        crops,
        options.strangers,
        options.folds,
        options.seed,
        options.gallery_fraction,
        options.gap_sessions,
    )
    folds = [
        _Fold(
            scored,
            {
                level: scored_level.decisions.threshold_for(options.precision)
                for level, scored_level in scored.levels.items()
            },
            self_set,
        )
        for scored, self_set in zip(
            _scored_folds(crops, vectors, splits, options.k),
            self_set_thresholds(crops, vectors, splits, options),
            strict=True,
        )
    ]
    return Scores(
        len(crops),
        len({crop.identity for crop in crops}),
        len({crop.session for crop in crops} - {""}),
        splits[0].time_disjoint,
        folds,
    )


def own_thresholds(scores: Scores) -> dict[str, float]:
    """This farm's threshold per level: the median of its folds' oracle thresholds."""
    found: dict[str, list[float]] = {}
    for fold in scores.folds:
        for level, threshold in fold.oracle.items():
            if threshold is not None:
                found.setdefault(level, []).append(threshold)
    return {level: median(values) for level, values in found.items()}


def other_farms(thresholds: Sequence[dict[str, float]]) -> dict[str, float]:
    """One setting for a farm nobody measured: the median of the others' thresholds."""
    levels = {level for farm in thresholds for level in farm}
    return {
        level: median(farm[level] for farm in thresholds if level in farm)
        for level in levels
    }


def _naming(decisions: Decisions, threshold: float | None) -> dict[str, Any] | None:
    return None if threshold is None else decisions.at(threshold).as_dict()


def report(
    scores: Scores,
    options: Options,
    from_other_farms: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Each fold's naming at four thresholds, from most to least informed.

    - oracle: chosen on the fold it is scored on; its coverage is a ceiling.
    - carried: the median of the other folds' oracle thresholds, as a fixed
      setting does on the same farm on a new day with new strangers.
    - self_set: chosen on the gallery alone (see `self_set_thresholds`), as a farm can do
      after naming its cows.
    - other_farms: chosen on other farms, as a shipped default does.
    """
    folds = []
    for index, fold in enumerate(scores.folds):
        result = fold.scored
        levels = {}
        for level, scored_level in result.levels.items():
            decisions, night = scored_level.decisions, scored_level.night
            others = [
                threshold
                for position, other in enumerate(scores.folds)
                if position != index
                and (threshold := other.oracle.get(level)) is not None
            ]
            carried = median(others) if others else None
            self_set = fold.self_set.get(level)
            entry: dict[str, Any] = {
                "rank1": scored_level.rank1,
                "top3": scored_level.top3,
                "oracle": _naming(decisions, fold.oracle[level]),
                "carried": _naming(decisions, carried),
                "self_set": _naming(decisions, self_set),
                "other_farms": _naming(decisions, (from_other_farms or {}).get(level)),
            }
            applied = next(
                (
                    threshold
                    for threshold in (self_set, carried, fold.oracle[level])
                    if threshold is not None
                ),
                None,
            )
            if night is not None:
                entry["day"] = _naming(decisions.subset(~night), applied)
                entry["night"] = _naming(decisions.subset(night), applied)
            levels[level] = entry
        folds.append(
            {
                "name": result.split.name,
                "gallery": len(result.split.gallery),
                "queries": len(result.split.queries),
                "strangers": sorted(result.split.strangers),
                "rank1": result.rank1,
                "map": result.map,
                "levels": levels,
            }
        )
    return {
        "crops": scores.crops,
        "identities": scores.identities,
        "sessions": scores.sessions,
        "time_disjoint": scores.time_disjoint,
        "options": asdict(options),
        "thresholds": {
            "own": own_thresholds(scores),
            "other_farms": from_other_farms,
        },
        "folds": folds,
        "summary": summarise(folds),
    }


def evaluate(
    crops: Sequence[Crop], vectors: NDArray[np.float32], options: Options
) -> dict[str, Any]:
    """Score one farm on its own; see `report` for the thresholds."""
    return report(score(crops, vectors, options), options)


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def summarise(folds: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "rank1": _mean([fold["rank1"] for fold in folds]),
        "map": _mean([fold["map"] for fold in folds]),
    }
    for level in folds[0]["levels"]:
        reports = [fold["levels"][level] for fold in folds]
        entry: dict[str, float | None] = {
            "rank1": _mean([report["rank1"] for report in reports]),
            "top3": _mean([report["top3"] for report in reports]),
        }
        for kind in ("oracle", "carried", "self_set", "other_farms", "day", "night"):
            namings = [report.get(kind) for report in reports]
            for field in ("coverage", "precision", "strangers_named"):
                entry[f"{kind}_{field}"] = _mean(
                    [naming[field] if naming else None for naming in namings]
                )
        summary[level] = entry
    return summary
