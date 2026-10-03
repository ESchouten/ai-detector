"""Research-only border evidence and short whole-track continuity controls."""

from collections import Counter
from dataclasses import replace

import numpy as np

from aidetector.adapters.inference.identity_observations import GalleryIdentifier
from aidetector.domain.models import IdentityMatch


class BorderTorsoIdentifier:
    """Preserve exact crop pixels while removing only the image-edge rejection.

    A two-pixel frame around the image moves all original crop rectangles off
    the boundary. The crops exclude that frame; size, overlap, encoder input,
    sample cadence and actual GalleryIdentifier matching remain unchanged.
    Only the research torso adapter passes observations through this wrapper.
    """

    def __init__(self, identifier):
        self.identifier = identifier

    def identify(self, source, observation):
        height, width = observation.image.shape[:2]
        if any(
            not (0 <= box.x1 < box.x2 <= width and 0 <= box.y1 < box.y2 <= height)
            for box in observation.boxes
        ):
            raise ValueError("Torso coordinates must lie inside the original image")
        padded = np.pad(
            observation.image, ((2, 2), (2, 2), (0, 0)), constant_values=127
        )
        shifted = tuple(
            replace(box, x1=box.x1 + 2, x2=box.x2 + 2, y1=box.y1 + 2, y2=box.y2 + 2)
            for box in observation.boxes
        )
        result = self.identifier.identify(
            source, replace(observation, image=padded, boxes=shifted)
        )
        return replace(
            observation,
            boxes=tuple(
                replace(original, identity=identified.identity)
                for original, identified in zip(
                    observation.boxes, result.boxes, strict=True
                )
            ),
        )


class ObservedIdentifier(GalleryIdentifier):
    """Expose already-computed pending matches for simultaneous hold conflicts."""

    def _reject_conflicts(self, matches):
        self.pending = dict(matches)
        return super()._reject_conflicts(matches)


def torso_presence(raw):
    """Any intersecting torso is evidence, including ambiguous partial overlap.

    Only zero geometric intersection means genuinely absent evidence. This is
    stricter than the separate90%-containment rule used to accept a crop.
    """
    whole = [box for box in raw if box.label == "whole_visible_cow"]
    torsos = [box for box in raw if box.label == "coat_torso"]
    return [
        sum(
            min(torso.x2, box.x2) > max(torso.x1, box.x1)
            and min(torso.y2, box.y2) > max(torso.y1, box.y1)
            for torso in torsos
        )
        for box in whole
    ]


class VisibleTrackHold:
    """Hold only a recently confirmed name through absent torso evidence.

    Present but unusable/ambiguous/unconfirmed evidence clears a held name.
    Missing/reused tracks, duplicate IDs, duplicate names, nonmonotonic time and
    gaps reset continuity. Neither held output nor future samples refresh TTL.
    """

    def __init__(self, seconds=1.0):
        self.seconds = seconds
        self.previous_at = None
        self.confirmed = {}

    def _proposed_match(self, box, torso_count, at, tracks):
        track, match = box.track_id, box.identity
        if track is None or tracks[track] != 1:
            return IdentityMatch()
        if match.identity_id:
            self.confirmed[track] = (at, match)
        elif torso_count:
            self.confirmed.pop(track, None)
        else:
            previous = self.confirmed.get(track)
            if (
                previous is not None
                and (at - previous[0]).total_seconds() <= self.seconds
            ):
                return previous[1]
            self.confirmed.pop(track, None)
        return match

    def apply(self, observation, presence, pending):
        if len(observation.boxes) != len(presence) or len(presence) != len(pending):
            raise ValueError("Whole-animal boxes and torso-presence mapping differ")
        at = observation.date
        if self.previous_at is not None and at <= self.previous_at:
            self.confirmed.clear()
            self.previous_at = at
            return replace(
                observation,
                boxes=tuple(
                    replace(box, identity=IdentityMatch()) for box in observation.boxes
                ),
            )
        if (
            self.previous_at is not None
            and (at - self.previous_at).total_seconds() > self.seconds
        ):
            self.confirmed.clear()
        self.previous_at = at
        tracks = Counter(
            box.track_id for box in observation.boxes if box.track_id is not None
        )
        self.confirmed = {
            track: value
            for track, value in self.confirmed.items()
            if tracks[track] == 1
        }
        proposed = [
            self._proposed_match(box, torso_count, at, tracks)
            for box, torso_count in zip(observation.boxes, presence, strict=True)
        ]
        evidence = [
            candidate.identity_id or match.identity_id
            for candidate, match in zip(pending, proposed, strict=True)
        ]
        identities = Counter(value for value in evidence if value is not None)
        resolved = []
        for box, match, value in zip(
            observation.boxes, proposed, evidence, strict=True
        ):
            if value is not None and identities[value] > 1:
                self.confirmed.pop(box.track_id, None)
                match = IdentityMatch()
            resolved.append(match)
        return replace(
            observation,
            boxes=tuple(
                replace(box, identity=match)
                for box, match in zip(observation.boxes, resolved, strict=True)
            ),
        )
