"""Decide which tracked animals carry a name, one sampled frame at a time.

A name needs repeated agreement of one track's own crops and is withdrawn as
soon as the evidence stops supporting it. Nothing here looks ahead in time.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Limits:
    floor: float  # smoothed similarity a new name needs
    margin: float  # lead over the second most similar cow a new name needs
    observations: int = 3  # consecutive agreeing samples before a name is shown
    memory: float = 0.5  # weight of the track's earlier samples
    max_gap: float = 5.0  # seconds a track may be unseen and keep its evidence
    # One cow cannot be two animals in the same frame: the animal that looks most
    # like the cow keeps the claim, even while its own evidence is too weak to show.
    exclusive: bool = True
    keep_floor: float | None = None  # a shown name survives down to these limits
    keep_margin: float | None = None


@dataclass
class _Track:
    smoothed: np.ndarray
    seen: float
    candidate: int = -1
    agreeing: int = 0
    shown: bool = False


class Namer:
    def __init__(self, classes, limits):
        self.classes = list(classes)
        self.limits = limits
        self._tracks = {}

    def update(self, seconds, observations):
        """`observations`: (track, scores) pairs of one frame; returns their names.

        A class named None competes like any other but is never shown: it stands
        for animals known not to belong to the herd. `scores` is None for a crop
        that is unfit as evidence; its track keeps what it knew but shows no name.
        """
        limits = self.limits
        proposals = []
        for track, scores in observations:
            if track is None:
                proposals.append((None, None, 0.0))
                continue
            state = self._tracks.get(track)
            if scores is None:
                if state is not None and seconds - state.seen <= limits.max_gap:
                    state.seen = seconds
                proposals.append((None, None, 0.0))
                continue
            if state is None or seconds - state.seen > limits.max_gap:
                state = self._tracks[track] = _Track(scores.astype(np.float64), seconds)
            else:
                state.smoothed = (
                    limits.memory * state.smoothed + (1 - limits.memory) * scores
                )
                state.seen = seconds
            order = np.argsort(-state.smoothed)
            best = state.smoothed[order[0]]
            lead = best - state.smoothed[order[1]]
            nameable = self.classes[order[0]] is not None
            holds = state.shown and state.candidate == order[0]
            floor = limits.keep_floor if holds and limits.keep_floor is not None else limits.floor
            margin = (
                limits.keep_margin if holds and limits.keep_margin is not None else limits.margin
            )
            if nameable and best >= floor and lead >= margin:
                state.agreeing = state.agreeing + 1 if state.candidate == order[0] else 1
                state.candidate = int(order[0])
            else:
                state.agreeing = 0
                state.candidate = -1
            state.shown = state.agreeing >= limits.observations
            proposals.append((state.candidate if state.shown else None, int(order[0]), float(best)))
        if limits.exclusive:
            strongest = {}
            for position, (_, likeness, best) in enumerate(proposals):
                if likeness is not None and best > strongest.get(likeness, (-2.0, -1))[0]:
                    strongest[likeness] = (best, position)
            proposals = [
                (
                    candidate
                    if likeness is not None and strongest[likeness][1] == position
                    else None,
                    likeness,
                    best,
                )
                for position, (candidate, likeness, best) in enumerate(proposals)
            ]
        for track in [
            track
            for track, state in self._tracks.items()
            if seconds - state.seen > limits.max_gap
        ]:
            del self._tracks[track]
        return [
            None if candidate is None else self.classes[candidate]
            for candidate, _, _ in proposals
        ]
