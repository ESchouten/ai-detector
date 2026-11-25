"""Group look-alike sightings so a person names each individual once."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

# Average similarity at which sightings join a group; the enrolment study found
# it gives few mixed groups for few names to type.
GROUPING = 0.6


def _merges(similarity: NDArray[np.floating]) -> list[tuple[int, int, float]]:
    """Every average-linkage merge, with the similarity it joined at.

    Found with the nearest-neighbour chain, which updates one row per merge
    instead of searching all pairs. The first item of a merge goes on
    representing the joined group.
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


def group(
    vectors: NDArray[np.float32], similarity: float = GROUPING
) -> list[list[int]]:
    """Indices of L2-normalised sighting embeddings, by group, largest first.

    Average linkage never joins two groups more readily than it joined their
    parts, so applying every merge at or above `similarity` cuts the tree there.
    Groups of the same size keep the order of their first member.
    """
    parent = list(range(len(vectors)))

    def root(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first, second, joined in _merges(vectors @ vectors.T):
        if joined >= similarity:
            parent[root(second)] = root(first)
    groups: dict[int, list[int]] = {}
    for item in range(len(vectors)):
        groups.setdefault(root(item), []).append(item)
    return sorted(groups.values(), key=len, reverse=True)
