"""Turn picture similarities into a score per enrolled animal, per crop or per track."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray


def similarities(
    queries: NDArray[np.float32], gallery: NDArray[np.float32]
) -> NDArray[np.float32]:
    """Cosine similarity of L2-normalised embeddings, queries by gallery."""
    return queries @ gallery.T


def identity_scores(
    similarity: NDArray[np.float32], gallery_identities: Sequence[str], k: int = 2
) -> tuple[tuple[str, ...], NDArray[np.float32]]:
    """Mean of each animal's k most similar gallery pictures, queries by animals.

    Comparing with an animal's nearest pictures rather than her average keeps a
    look-alike stranger further from the herd (the old herd study's finding).
    """
    names = tuple(sorted(set(gallery_identities)))
    labels = np.asarray(gallery_identities)
    scores = np.empty((similarity.shape[0], len(names)), dtype=np.float32)
    for column, name in enumerate(names):
        own = similarity[:, labels == name]
        top = min(k, own.shape[1])
        # Only the top k are needed, so partition instead of sorting whole rows.
        nearest = np.partition(own, own.shape[1] - top, axis=1)[:, -top:]
        scores[:, column] = nearest.mean(axis=1)
    return names, scores


def track_scores(
    scores: NDArray[np.float32], tracks: Sequence[str]
) -> tuple[tuple[int, ...], NDArray[np.float32]]:
    """Average crop scores over each track; a crop without a track stands alone.

    Returns the index of each group's first crop and the averaged scores.
    """
    groups: dict[str, list[int]] = {}
    for index, track in enumerate(tracks):
        groups.setdefault(track or f"\0{index}", []).append(index)
    firsts = tuple(indices[0] for indices in groups.values())
    return firsts, np.stack(
        [scores[indices].mean(axis=0) for indices in groups.values()]
    )
