"""Names as the application's own identity rules would show them.

The rules are imported from the detector, not copied: a crop gets a candidate
name from its similarities, two animals claiming one cow in a frame both lose
it, and a track shows a name after enough consecutive agreeing crops.
"""

import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from aidetector.adapters.inference.identity_observations import usable_crop
from aidetector.domain.identity import (
    TrackAgreement,
    choose_identity,
    reject_conflicting_matches,
)
from aidetector.domain.models import BoundingBox, IdentityMatch

OTHER = "another farm's cow"


@dataclass(frozen=True)
class Rules:
    min_similarity: float
    min_margin: float
    min_observations: int = 3
    hold: float = 0  # seconds a confirmed name survives weaker crops
    min_crop_size: int = 64
    max_overlap: float = 1.0
    whole_animal: bool = False  # refuse boxes that touch the frame border
    # The application once forgot a track the moment one frame lacked it.
    forget_absent: bool = False
    # The limit in pictures taken under infrared light; unset, `min_similarity`.
    min_similarity_infrared: float | None = None


def fit_crops(crops, rules):
    """Whether each crop passes the application's geometry check."""
    by_frame = defaultdict(list)
    for position, crop in enumerate(crops):
        by_frame[crop["index"]].append(position)
    fit = [False] * len(crops)
    for positions in by_frame.values():
        boxes = tuple(
            BoundingBox(*(round(value) for value in crops[position]["box"]))
            for position in positions
        )
        width, height = crops[positions[0]]["frame_size"]
        if not rules.whole_animal:
            # The application check always refuses border contact; widen the
            # frame so that only size and overlap decide.
            boxes = tuple(
                BoundingBox(box.x1 + 2, box.y1 + 2, box.x2 + 2, box.y2 + 2) for box in boxes
            )
            width, height = width + 4, height + 4
        for position, box in zip(positions, boxes, strict=True):
            fit[position] = usable_crop(
                box, boxes, width, height, rules.min_crop_size, rules.max_overlap
            )
    return fit


def name_crops(crops, scores, classes, rules, empty_frames=()):
    """The cow shown on every crop (None when unknown), in the order of `crops`.

    `empty_frames` lists the seconds of sampled frames without any box; the
    application sees those too, and they end every track it was following.

    `scores` has one column per entry of `classes` and a last column for the
    best-matching cow of another farm, which can win but is never shown.
    Also returns, per crop, how far it came: whether its geometry was fit,
    which cow it resembled most, and which candidate survived each rule.
    """
    by_frame = defaultdict(list)
    for position, crop in enumerate(crops):
        by_frame[crop["index"]].append(position)
    fit = fit_crops(crops, rules)
    agreement = TrackAgreement(rules.min_observations, max_gap=5, hold=rules.hold)
    start = datetime(2000, 1, 1)
    names = [None] * len(crops)
    stages = [None] * len(crops)
    labels = [str(cow) for cow in classes] + [OTHER]
    followed = set()

    def cow(match):
        return None if match.identity_id is None else classes[labels.index(match.identity_id)]

    moments = sorted(
        [(crops[positions[0]]["seconds"], positions) for positions in by_frame.values()]
        + [(seconds, []) for seconds in empty_frames]
    )
    for seconds, positions in moments:
        at = start + timedelta(seconds=seconds)
        present = {crops[position]["track"] for position in positions}
        if rules.forget_absent:
            for track in followed - present:
                agreement.update("camera", track, at, IdentityMatch())
        followed = present
        limit = rules.min_similarity
        night = positions and crops[positions[0]]["infrared"]
        if night and rules.min_similarity_infrared is not None:
            limit = rules.min_similarity_infrared
        candidates = []
        for position in positions:
            if not fit[position]:
                candidates.append(IdentityMatch())
                continue
            match = choose_identity(
                [
                    IdentityMatch(label, label, float(score))
                    for label, score in zip(labels, scores[position], strict=True)
                ],
                limit,
                rules.min_margin,
            )
            if match.identity_id == OTHER:
                match = IdentityMatch(similarity=match.similarity)
            candidates.append(match)
        resolved = reject_conflicting_matches(tuple(candidates))
        claimed = {candidate.identity_id for candidate in candidates}
        for position, candidate, match in zip(positions, candidates, resolved, strict=True):
            likeness = labels[int(scores[position].argmax())]
            shown = agreement.update(
                "camera",
                crops[position]["track"],
                at,
                match,
                likeness if fit[position] and likeness not in claimed else None,
            )
            names[position] = cow(shown)
            likeness = int(scores[position][: len(classes)].argmax())
            stages[position] = {
                "fit": fit[position],
                "resembles": classes[likeness],
                "candidate": cow(candidate),
                "unchallenged": cow(match),
                "shown": names[position],
            }
        agreement.discard_stale("camera", at)
    return names, stages


def funnel(stages, partner, visible, located, enrolled):
    """Where the visible enrolled animals are lost, stage by stage."""
    counts = {
        "visible": sum(visible[cow] for cow in enrolled),
        "located": sum(located[cow] for cow in enrolled),
        "fit_crop": 0,
        "resembles_itself": 0,
        "accepted_candidate": 0,
        "unchallenged": 0,
        "shown": 0,
    }
    for stage, cow in zip(stages, partner, strict=True):
        if cow not in enrolled or not stage["fit"]:
            continue
        counts["fit_crop"] += 1
        counts["resembles_itself"] += stage["resembles"] == cow
        counts["accepted_candidate"] += stage["candidate"] == cow
        counts["unchallenged"] += stage["unchallenged"] == cow
        counts["shown"] += stage["shown"] == cow
    return counts
