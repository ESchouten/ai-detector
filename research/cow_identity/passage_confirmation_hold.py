"""Fixed research control: carry a confirmed identity through weak track evidence."""

from collections import Counter

from passage_torso_continuity import VisibleTrackHold

from aidetector.domain.models import IdentityMatch


def intersect(first, second):
    return min(first.x2, second.x2) > max(first.x1, second.x1) and min(
        first.y2, second.y2
    ) > max(first.y1, second.y1)


class ConfirmationHold(VisibleTrackHold):
    """Five-second evidence TTL, with a separate 0.6-second observation-gap bound.

    Only a real three-sample confirmation refreshes TTL. A strong different
    pending identity clears an old name immediately; low information alone does
    not. Spatial jumps clear both the holder and actual matcher agreement, so an
    inherited stale confirmation cannot restore a name on the following frame.
    """

    def __init__(self):
        super().__init__(seconds=5.0)
        self.last_observation = None
        self.previous_boxes = {}
        self.pending = {}

    def before_observation(self, identifier, source, observation):
        boxes = [
            box
            for box in observation.boxes
            if box.label == "whole_visible_cow" and box.track_id is not None
        ]
        counts = Counter(box.track_id for box in boxes)
        current = {box.track_id: box for box in boxes if counts[box.track_id] == 1}
        unsafe = set(self.previous_boxes) - set(current)
        unsafe.update(track for track, count in counts.items() if count != 1)
        unsafe.update(
            track
            for track, box in current.items()
            if track in self.previous_boxes
            and not intersect(box, self.previous_boxes[track])
        )
        if self.last_observation is not None:
            gap = (observation.date - self.last_observation).total_seconds()
            if not 0 < gap <= 0.6:
                unsafe.update(self.previous_boxes)
                unsafe.update(current)
        for track in unsafe:
            self.confirmed.pop(track, None)
            identifier._tracks.pop((source, track), None)
            identifier.agreement.update(
                source, track, observation.date, IdentityMatch()
            )
        self.previous_boxes, self.last_observation = current, observation.date

    def _proposed_match(self, box, torso_count, at, tracks):
        track, match = box.track_id, box.identity
        if track is None or tracks[track] != 1:
            return IdentityMatch()
        previous = self.confirmed.get(track)
        candidate = self.pending[track]
        if (
            previous is not None
            and candidate.identity_id
            and candidate.identity_id != previous[1].identity_id
        ):
            self.confirmed.pop(track, None)
            previous = None
        if match.identity_id:
            self.confirmed[track] = (at, match)
        elif (
            previous is not None and (at - previous[0]).total_seconds() <= self.seconds
        ):
            return previous[1]
        else:
            self.confirmed.pop(track, None)
        return match

    def apply(self, observation, presence, pending):
        self.pending = {
            box.track_id: candidate
            for box, candidate in zip(observation.boxes, pending, strict=True)
        }
        return super().apply(observation, presence, pending)
