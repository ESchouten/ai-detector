import numpy as np

from policy import Limits
from video_eval import associate, crop_geometry, name_crops, tally
from video_score import score_video

TRUTH = {
    0: [(1, 0, 0, 10, 10), (2, 20, 0, 30, 10), (9, 40, 0, 50, 10)],
    15: [(1, 0, 0, 10, 10), (9, 40, 0, 50, 10)],
    30: [(2, 20, 0, 30, 10)],
}


def crop(index, box, track):
    return {
        "index": index,
        "seconds": index / 15,
        "box": list(box),
        "track": track,
        "frame_size": [100, 60],
    }


CROPS = [
    crop(0, (0, 0, 10, 10), 1),
    crop(0, (20, 0, 30, 10), 2),
    crop(0, (41, 0, 50, 10), 3),
    crop(0, (70, 30, 80, 40), 4),
    crop(15, (0, 0, 10, 10), 1),
    crop(15, (40, 0, 50, 10), 3),
    crop(30, (20, 0, 30, 10), 2),
]
NAMES = [1, 1, 2, 2, 1, None, 2]


def test_recounting_agrees_with_the_frame_by_frame_reference():
    partner, visible, located, around = associate(CROPS, sorted(TRUTH), TRUTH.__getitem__)
    quick = tally(NAMES, partner, visible, located, around, {1, 2}, frozenset())
    frames = []
    for index in sorted(TRUTH):
        frames.append(
            (
                index,
                [
                    {"box": item["box"], "name": name}
                    for item, name in zip(CROPS, NAMES, strict=True)
                    if item["index"] == index
                ],
            )
        )
    reference = score_video(frames, TRUTH.__getitem__, {1, 2})
    assert quick == reference
    assert quick["correct"] == 3
    assert quick["wrong_enrolled"] == 1
    assert quick["named_withheld"] == 1
    assert quick["named_unannotated"] == 1
    # Cow 2 is annotated elsewhere in that frame, so the stray name is an error.
    assert quick["unpaired_elsewhere"] == 1
    assert quick["precision"] == 3 / 6


def test_frames_without_any_detection_still_count_their_animals():
    partner, visible, located, _ = associate([], sorted(TRUTH), TRUTH.__getitem__)
    assert partner == []
    assert visible[1] == 2 and located[1] == 0


def test_unfit_crops_are_not_used_as_evidence():
    scores = np.tile(np.array([0.9, 0.1, -1.0]), (len(CROPS), 1))
    limits = Limits(floor=0.5, margin=0.2, observations=1, memory=0.0, exclusive=False)
    side, crowding, border = crop_geometry(CROPS)
    assert border.tolist() == [True, True, True, False, True, True, True]
    names = name_crops(CROPS, scores, ["a", "b", None], limits, ~border)
    assert names == [None, None, None, "a", None, None, None]
