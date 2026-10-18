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
from reid.metrics import Decisions, mean_average_precision, rank1, top_k
from reid.splits import Split, open_set_splits


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
    top3: float | None


@dataclass(frozen=True)
class _Scored:
    split: Split
    rank1: float | None
    map: float | None
    levels: dict[str, _Level]


def _score(
    crops: Sequence[Crop], vectors: NDArray[np.float32], split: Split, k: int
) -> _Scored:
    gallery = [crops[i].identity for i in split.gallery]
    queries = [crops[i] for i in split.queries]
    truth = [crop.identity for crop in queries]
    similarity = similarities(
        vectors[list(split.queries)], vectors[list(split.gallery)]
    )
    names, scores = identity_scores(similarity, gallery, k)
    night = np.array([crop.night is True for crop in queries])
    known_light = any(crop.night is not None for crop in queries)
    levels = {
        "crop": _Level(
            Decisions.of(names, scores, truth),
            night if known_light else None,
            top_k(names, scores, truth, 3),
        )
    }
    if any(crop.track for crop in queries):
        firsts, averaged = track_scores(scores, [crop.track for crop in queries])
        track_truth = [truth[i] for i in firsts]
        levels["track"] = _Level(
            Decisions.of(names, averaged, track_truth),
            night[list(firsts)] if known_light else None,
            top_k(names, averaged, track_truth, 3),
        )
    return _Scored(
        split,
        rank1(names, scores, truth),
        mean_average_precision(similarity, gallery, truth),
        levels,
    )


def _naming(decisions: Decisions, threshold: float | None) -> dict[str, Any] | None:
    return None if threshold is None else decisions.at(threshold).as_dict()


def evaluate(
    crops: Sequence[Crop], vectors: NDArray[np.float32], options: Options
) -> dict[str, Any]:
    """Report each fold, and a threshold carried over from the other folds.

    The oracle threshold is chosen on the fold it is scored on, so its coverage is
    a ceiling. The carried-over threshold is the median of the other folds'
    oracle thresholds, which is closer to what a fixed setting does on a new day
    with new strangers.
    """
    splits = open_set_splits(
        crops,
        options.strangers,
        options.folds,
        options.seed,
        options.gallery_fraction,
        options.gap_sessions,
    )
    scored = [_score(crops, vectors, split, options.k) for split in splits]
    oracle = [
        {
            level: scored_level.decisions.threshold_for(options.precision)
            for level, scored_level in result.levels.items()
        }
        for result in scored
    ]
    folds = []
    for index, result in enumerate(scored):
        levels = {}
        for level, scored_level in result.levels.items():
            decisions, night = scored_level.decisions, scored_level.night
            others = [
                threshold
                for other, thresholds in enumerate(oracle)
                if other != index and (threshold := thresholds.get(level)) is not None
            ]
            carried = median(others) if others else None
            report: dict[str, Any] = {
                "top3": scored_level.top3,
                "oracle": _naming(decisions, oracle[index][level]),
                "carried": _naming(decisions, carried),
            }
            applied = carried if carried is not None else oracle[index][level]
            if night is not None:
                report["day"] = _naming(decisions.subset(~night), applied)
                report["night"] = _naming(decisions.subset(night), applied)
            levels[level] = report
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
        "crops": len(crops),
        "identities": len({crop.identity for crop in crops}),
        "sessions": len({crop.session for crop in crops} - {""}),
        "time_disjoint": splits[0].time_disjoint,
        "options": asdict(options),
        "folds": folds,
        "summary": summarise(folds),
    }


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
            "top3": _mean([report["top3"] for report in reports])
        }
        for kind in ("oracle", "carried", "day", "night"):
            namings = [report.get(kind) for report in reports]
            for field in ("coverage", "precision", "strangers_named"):
                entry[f"{kind}_{field}"] = _mean(
                    [naming[field] if naming else None for naming in namings]
                )
        summary[level] = entry
    return summary
