"""Small, frozen-gallery identification benchmark; no training or image I/O."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Scores:
    truth: np.ndarray
    predicted: np.ndarray
    similarity: np.ndarray
    margin: np.ndarray
    known: np.ndarray
    cameras: np.ndarray


def normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.all(np.isfinite(vectors)) or np.any(norms == 0):
        raise ValueError("Embeddings must be finite and nonzero")
    return vectors / norms


def score(
    gallery: np.ndarray,
    gallery_ids: np.ndarray,
    queries: np.ndarray,
    query_ids: np.ndarray,
    cameras: np.ndarray,
) -> Scores:
    """Best reference per identity; runner-up always belongs to another cow."""
    identities = np.unique(gallery_ids)
    if len(identities) < 2:
        raise ValueError("Evaluation needs at least two enrolled identities")
    similarities = normalize(queries) @ normalize(gallery).T
    by_identity = np.stack(
        [
            similarities[:, gallery_ids == identity].max(axis=1)
            for identity in identities
        ],
        axis=1,
    )
    order = np.argsort(-by_identity, axis=1, kind="stable")
    rows = np.arange(len(queries))
    best = by_identity[rows, order[:, 0]]
    return Scores(
        query_ids,
        identities[order[:, 0]],
        best,
        best - by_identity[rows, order[:, 1]],
        np.isin(query_ids, identities),
        cameras,
    )


def metrics(scores: Scores, threshold: float, margin: float) -> dict:
    accepted = (scores.similarity >= threshold) & (scores.margin >= margin)
    correct = scores.predicted == scores.truth
    known = scores.known

    def count(mask):
        return int(np.count_nonzero(mask))

    def ratio(n, d):
        return float(n / d) if d else None

    correct_accepts = count(accepted & correct & known)
    wrong_known = count(accepted & ~correct & known)
    unknown_accepts = count(accepted & ~known)
    return {
        "observations": len(known),
        "known": count(known),
        "unknown": count(~known),
        "correct_accepts": correct_accepts,
        "wrong_known_accepts": wrong_known,
        "unknown_false_accepts": unknown_accepts,
        "accepted_precision": ratio(correct_accepts, count(accepted)),
        "known_coverage": ratio(correct_accepts, count(known)),
        "unknown_false_acceptance_rate": ratio(unknown_accepts, count(~known)),
        "known_rank1": ratio(count(correct & known), count(known)),
        "abstentions": count(~accepted),
    }


def calibrate(scores: Scores) -> tuple[float, float]:
    """Maximize correct coverage with zero observed calibration false accepts.

    Fixed grid, no test input. Ties favor stricter similarity then margin.
    Reject-all is a valid outcome when the representation is inadequate.
    """
    if not scores.known.any() or scores.known.all():
        raise ValueError("Calibration requires known and withheld unknown cows")
    candidates = []
    for threshold in np.arange(0.0, 1.001, 0.01):
        for margin in np.arange(0.0, 1.001, 0.01):
            accepted = (scores.similarity >= threshold) & (scores.margin >= margin)
            correct = scores.known & (scores.predicted == scores.truth)
            if np.any(accepted & ~correct):
                continue
            candidates.append(
                (int(np.sum(accepted & correct)), float(threshold), float(margin))
            )
    _, threshold, margin = max(candidates, default=(0, 1.01, 1.01))
    return threshold, margin


def report(scores: Scores, threshold: float, margin: float) -> dict:
    result = metrics(scores, threshold, margin)
    result["per_camera"] = {}
    for camera in np.unique(scores.cameras):
        chosen = scores.cameras == camera
        subset = Scores(
            *(
                getattr(scores, field)[chosen]
                for field in (
                    "truth",
                    "predicted",
                    "similarity",
                    "margin",
                    "known",
                    "cameras",
                )
            )
        )
        result["per_camera"][str(camera)] = metrics(subset, threshold, margin)
    return result
