from pathlib import Path

import numpy as np
import pytest

from reid.cli import choice_table
from reid.pictures import (
    AI_DETECTOR,
    Choice,
    Picture,
    choices,
    choose,
    compare,
    overlap,
    pairs,
    read_pictures,
    shape,
    whole,
    windows,
    write_pictures,
)
from reid.tracking import Detection

pytest.importorskip("cv2")

FPS = 20


def picture(
    track="a",
    frame=0,
    size=100,
    *,
    edge=False,
    overlap=0.0,
    solidity=0.9,
    pieces=1,
    confidence=0.8,
):
    return Picture(
        Path(f"{track}/{frame:07d}.jpg"),
        track,
        frame,
        frame / FPS,
        0,
        0,
        size,
        size,
        confidence,
        edge,
        overlap,
        solidity,
        pieces,
        0.6,
    )


def test_a_whole_mask_is_one_solid_piece():
    mask = np.zeros((60, 80), bool)
    mask[10:50, 10:70] = True

    solidity, pieces, fill = shape(mask)

    assert solidity == pytest.approx(1.0)
    assert pieces == 1
    assert fill == pytest.approx(1.0)


def test_rails_cut_a_mask_into_pieces_and_make_it_less_solid():
    mask = np.zeros((60, 80), bool)
    mask[10:50, 10:70] = True
    mask[20:24] = False
    mask[34:38] = False

    solidity, pieces, fill = shape(mask)

    assert pieces == 3
    assert solidity < 0.85
    assert fill < 0.85


def test_specks_are_not_pieces_and_an_empty_mask_has_none():
    mask = np.zeros((60, 80), bool)
    mask[10:50, 10:70] = True
    mask[55, 75] = True

    assert shape(mask)[1] == 1
    assert shape(np.zeros((5, 5), bool)) == (0.0, 0, 0.0)


def test_overlap_is_the_largest_share_under_any_one_other_box():
    box = Detection(1, 0, 0, 10, 10)
    left = Detection(2, -5, 0, 5, 10)
    corner = Detection(3, 5, 5, 15, 15)

    assert overlap(box, [box]) == 0
    assert overlap(box, [box, left, corner]) == pytest.approx(0.5)


def test_ai_detectors_choice_takes_clear_pictures_first_spread_over_time():
    pictures = [
        picture(frame=0, size=300, edge=True),
        *(picture(frame=10 * i, size=100 + i) for i in range(1, 11)),
    ]

    chosen = choose(pictures, AI_DETECTOR)

    # The eight largest clear ones are the pool; four are taken across it.
    assert [pictures[i].frame for i in chosen] == [30, 50, 80, 100]


def test_a_cut_up_mask_gives_way_to_a_whole_one_even_when_larger():
    pictures = [
        picture(frame=0, size=200, pieces=3, solidity=0.5),
        picture(frame=10, size=100),
        picture(frame=20, size=300, edge=True),
    ]

    assert choose(pictures, AI_DETECTOR, count=1) == [0]
    assert choose(pictures, Choice("whole", whole(0.8), AI_DETECTOR.key), 1) == [1]
    assert choose(pictures, Choice("whole", whole(0.8), AI_DETECTOR.key), 3) == [
        1,
        0,
        2,
    ]


def test_tracks_are_cut_into_windows_of_at_least_two_pictures():
    pictures = [
        picture("a", 0),
        picture("a", 100),
        picture("a", 220),
        picture("b", 300),
        picture("b", 310),
    ]

    found = windows(pictures, seconds=10)

    assert [(w.track, w.start, w.pictures) for w in found] == [
        ("a", 0, (0, 1)),
        ("b", 15, (3, 4)),
    ]


def test_pairs_are_the_same_track_later_and_tracks_in_view_together():
    pictures = [
        *(picture("a", frame) for frame in range(0, 2400, 10)),
        *(picture("b", frame) for frame in range(0, 400, 10)),
        *(picture("c", frame) for frame in range(2000, 2400, 10)),
    ]
    found = windows(pictures, seconds=10)
    named = {(w.track, int(w.start)): i for i, w in enumerate(found)}

    same, different = pairs(pictures, found, gap=60)

    assert (named["a", 60], named["a", 0]) in same
    assert (named["a", 110], named["a", 50]) in same
    assert all(found[x].track == found[y].track == "a" for x, y in same)
    assert (
        sorted((found[x].track, found[y].track) for x, y in different)
        == [("a", "b")] * 2 + [("a", "c")] * 2
    )


def herd(seed=0):
    """Two cows in view together for two minutes. Cut-up pictures are larger
    but show mostly rails, the same for both cows."""
    rng = np.random.default_rng(seed)
    pictures, vectors = [], []
    for track, direction in (("a", 0), ("b", 1)):
        for frame in range(0, 2400, 10):
            cut = (frame // 10) % 2 == 0
            pictures.append(
                picture(
                    track,
                    frame,
                    size=150 if cut else 100,
                    pieces=3 if cut else 1,
                    solidity=0.5 if cut else 0.9,
                )
            )
            vector = np.zeros(8, np.float32)
            vector[2 if cut else direction] = 1
            vectors.append(vector + rng.normal(0, 0.3, 8).astype(np.float32))
    return pictures, np.stack(vectors)


def test_choosing_whole_pictures_tells_the_cows_apart_better():
    pictures, vectors = herd()

    result = compare(pictures, vectors, choices((0.8,)), window=10, gap=60)

    rows = {row["choice"]: row for row in result["choices"]}
    assert rows["one piece, solidity 0.8"]["rank1"] == 1.0
    assert rows["one piece, solidity 0.8"]["best_found"] == 1.0
    assert rows["ai-detector"]["rank1"] < 0.8
    assert rows["ai-detector"]["auc"] < rows["one piece, solidity 0.8"]["auc"]
    pieces = {bucket["value"]: bucket for bucket in result["features"]["pieces"]}
    assert pieces["1"]["first"] > pieces["3+"]["first"]
    assert result["later"] == {
        "tracks": 2,
        "first_window_without_whole": 0,
        "whole_later": 0,
    }
    table = choice_table(result)
    assert "| one piece, solidity 0.8 | 100.0 | 100.0 |" in table
    assert "| pieces | 3+ |" in table


def test_later_counts_tracks_that_show_a_whole_picture_only_later():
    pictures = [
        *(picture("a", frame, pieces=2) for frame in range(0, 200, 10)),
        picture("a", 300),
        picture("a", 310),
        *(picture("b", frame, edge=True) for frame in range(0, 400, 10)),
    ]
    vectors = np.eye(len(pictures), 8, dtype=np.float32) + 0.1

    result = compare(pictures, vectors, [AI_DETECTOR], window=10, gap=60)

    assert result["later"] == {
        "tracks": 2,
        "first_window_without_whole": 2,
        "whole_later": 1,
    }


def test_pictures_are_written_and_read_with_paths_beside_the_file(tmp_path):
    pictures = [
        picture("a", 10, edge=True, overlap=0.3),
        picture("b", 20, pieces=2, confidence=0.55),
    ]
    pictures = [
        Picture(tmp_path / "crops" / p.path, *(getattr(p, f) for f in FIELDS))
        for p in pictures
    ]

    write_pictures(tmp_path / "pictures.csv", pictures)

    assert read_pictures(tmp_path / "pictures.csv") == pictures
    assert "crops/a/0000010.jpg" in (tmp_path / "pictures.csv").read_text()


FIELDS = (
    "track",
    "frame",
    "seconds",
    "x1",
    "y1",
    "x2",
    "y2",
    "confidence",
    "edge",
    "overlap",
    "solidity",
    "pieces",
    "fill",
)
