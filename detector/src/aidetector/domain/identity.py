"""Conservative identity decisions from gallery scores and observed track history."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from aidetector.domain.models import IdentityMatch


def choose_identity(
    scores: Sequence[IdentityMatch], min_similarity: float, min_margin: float
) -> IdentityMatch:
    """Require an absolute match and separation from another gallery identity.

    The adapter supplies one finite similarity per distinct named identity.
    Multiple references for one animal are not independent impostor comparisons.
    """
    ranked = sorted(
        scores, key=lambda score: cast(float, score.similarity), reverse=True
    )
    if not ranked:
        return IdentityMatch()
    best = ranked[0]
    similarity = cast(float, best.similarity)
    if (
        len(ranked) < 2
        or similarity < min_similarity
        or similarity - cast(float, ranked[1].similarity) < min_margin
    ):
        return IdentityMatch(similarity=similarity)
    return best


def reject_conflicting_matches(
    matches: Sequence[IdentityMatch],
) -> tuple[IdentityMatch, ...]:
    """Two subjects visible together cannot receive the same animal identity."""
    counts = Counter(
        match.identity_id for match in matches if match.identity_id is not None
    )
    return tuple(
        IdentityMatch(similarity=match.similarity)
        if match.identity_id is not None and counts[match.identity_id] > 1
        else match
        for match in matches
    )


@dataclass
class _Agreement:
    identity_id: str
    last_at: datetime
    observations: int = 1


class TrackAgreement:
    """Confirm one identity after distinct, chronological samples of a track.

    One inference worker owns access. Source and tracker ID together identify
    a temporary track; a long observation gap requires fresh agreement.
    """

    def __init__(self, min_observations: int = 3, max_gap: float = 5):
        self.min_observations = min_observations
        self.max_gap = max_gap
        self._tracks: dict[tuple[str, int], _Agreement] = {}

    def update(
        self,
        source: str,
        track_id: int | None,
        at: datetime,
        match: IdentityMatch,
    ) -> IdentityMatch:
        unknown = IdentityMatch(similarity=match.similarity)
        if track_id is None:
            return unknown
        key = (source, track_id)
        if match.identity_id is None:
            self._tracks.pop(key, None)
            return unknown
        previous = self._tracks.get(key)
        if previous is not None and at <= previous.last_at:
            return unknown
        if (
            previous is None
            or previous.identity_id != match.identity_id
            or (at - previous.last_at).total_seconds() > self.max_gap
        ):
            agreement = _Agreement(match.identity_id, at)
            self._tracks[key] = agreement
        else:
            agreement = previous
            agreement.last_at = at
            agreement.observations = min(
                agreement.observations + 1, self.min_observations
            )
        return match if agreement.observations >= self.min_observations else unknown

    def discard_stale(self, source: str, at: datetime) -> None:
        """Release tracks no longer observed by this source, including empty frames."""
        stale = [
            key
            for key, agreement in self._tracks.items()
            if key[0] == source
            and (at - agreement.last_at).total_seconds() > self.max_gap
        ]
        for key in stale:
            del self._tracks[key]

    def clear(self) -> None:
        """Forget decisions after gallery changes; old confirmations must not persist."""
        self._tracks.clear()
