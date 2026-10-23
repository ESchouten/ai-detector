"""Re-check each sighting's best few candidate cows by matching coat details.

The embedding shortlists the cows; keypoint matches between the sighting's
pictures and each candidate's most similar gallery pictures add a second
opinion. This module measures whether that helps before it goes into enrolment:
one time split with strangers, as in the benchmark, scored at a threshold chosen
on the same queries, so scoring rules are compared on equal terms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reid.enrollment import sightings
from reid.local import Matcher, coat_matches
from reid.manifest import Crop
from reid.matching import identity_scores, similarities
from reid.metrics import Decisions
from reid.splits import open_set_splits


@dataclass(frozen=True)
class Options:
    top: int = 3
    query_crops: int = 3
    gallery_crops: int = 3
    k: int = 2
    gallery_fraction: float = 0.5
    strangers: float = 0.25
    seed: int = 0
    precision: float = 0.99
    weights: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)
    margins: tuple[float, ...] = (0.0, 0.75)
    # Matches at which the coat score reaches 1; more count the same.
    saturation: float = 100.0


@dataclass(frozen=True)
class Candidates:
    """Each query sighting's best `top` cows by embedding, with their matches."""

    names: NDArray[np.str_]
    deep: NDArray[np.float32]
    matches: NDArray[np.float32]
    truth: NDArray[np.str_]
    known: NDArray[np.bool_]
    in_top: NDArray[np.bool_]


def candidates(
    crops: Sequence[Crop],
    vectors: NDArray[np.float32],
    matcher: Matcher,
    options: Options,
) -> Candidates:
    """Shortlist and match the first fold's queries against its gallery.

    A sighting is scored by the mean of its crops' scores, as in the benchmark.
    For each shortlisted cow, `query_crops` pictures of the sighting spread over
    it are matched with her `gallery_crops` pictures most similar to the
    sighting; a picture's count is its best match, the sighting's the mean.
    """
    split = open_set_splits(
        crops, options.strangers, 1, options.seed, options.gallery_fraction
    )[0]
    gallery = list(split.gallery)
    labels = np.array([crops[i].identity for i in gallery])
    names, scores = identity_scores(
        similarities(vectors[list(split.queries)], vectors[gallery]),
        labels.tolist(),
        options.k,
    )
    position = {index: row for row, index in enumerate(split.queries)}
    seen = sightings(crops, split.queries)
    deep_all = np.stack([scores[[position[i] for i in s]].mean(axis=0) for s in seen])
    order = np.argsort(-deep_all, axis=1, kind="stable")[:, : options.top]
    top_names = np.asarray(names)[order]
    local = coat_matches(
        matcher,
        crops,
        vectors,
        seen,
        gallery,
        labels.tolist(),
        top_names,
        options.query_crops,
        options.gallery_crops,
    )
    truth = np.array([crops[s[0]].identity for s in seen])
    return Candidates(
        top_names,
        np.take_along_axis(deep_all, order, axis=1),
        local,
        truth,
        np.isin(truth, names),
        (top_names == truth[:, None]).any(axis=1),
    )


def _named(
    found: Candidates, weight: float, margin: float, options: Options
) -> dict[str, Any]:
    """Rank-1 and naming at the precision target when coat matches add `weight`."""
    coat = np.minimum(found.matches, options.saturation) / options.saturation
    fused = found.deep + weight * coat
    order = np.argsort(-fused, axis=1, kind="stable")
    best = np.take_along_axis(fused, order[:, :1], axis=1)[:, 0]
    second = (
        np.take_along_axis(fused, order[:, 1:2], axis=1)[:, 0]
        if fused.shape[1] > 1
        else np.zeros_like(best)
    )
    chosen = np.take_along_axis(found.names, order[:, :1], axis=1)[:, 0]
    decisions = Decisions(best - margin * second, chosen == found.truth, found.known)
    threshold = decisions.threshold_for(options.precision)
    naming = decisions.at(threshold) if threshold is not None else None
    return {
        "weight": weight,
        "margin": margin,
        "rank1": float(decisions.correct[found.known].mean()),
        "named": naming.coverage if naming else 0.0,
        "right": naming.precision if naming else None,
        "strangers_named": naming.strangers_named if naming else None,
    }


def evaluate(found: Candidates, options: Options) -> dict[str, Any]:
    """Every weight and margin, with the share whose cow is shortlisted at all."""
    return {
        "queries": len(found.truth),
        "known": int(found.known.sum()),
        "in_top": float(found.in_top[found.known].mean()),
        "rows": [
            _named(found, weight, margin, options)
            for margin in options.margins
            for weight in options.weights
        ],
    }
