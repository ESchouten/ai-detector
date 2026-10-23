from pathlib import Path

import pytest

from reid.manifest import Crop
from reid.splits import open_set_splits, rotating_splits, time_split


def _crops(sessions: dict[str, list[str]]) -> list[Crop]:
    return [
        Crop(Path(f"{cow}-{session}.jpg"), cow, session)
        for session, cows in sessions.items()
        for cow in cows
    ]


def test_gallery_is_the_earliest_sessions():
    crops = _crops({"d1": ["a", "b"], "d2": ["a", "b"], "d3": ["a"], "d4": ["b"]})

    gallery, queries, disjoint = time_split(crops)

    assert disjoint
    assert {crops[i].session for i in gallery} == {"d1", "d2"}
    assert {crops[i].session for i in queries} == {"d3", "d4"}


def test_gap_sessions_are_left_out():
    crops = _crops({"d1": ["a", "b"], "d2": ["a", "b"], "d3": ["a", "b"]})

    gallery, queries, _ = time_split(crops, gallery_fraction=0.3, gap_sessions=1)

    assert {crops[i].session for i in gallery} == {"d1"}
    assert {crops[i].session for i in queries} == {"d3"}


def test_without_sessions_the_split_is_random_and_flagged():
    crops = [Crop(Path(f"{cow}{n}.jpg"), cow) for cow in "ab" for n in range(4)]

    gallery, queries, disjoint = time_split(crops)

    assert not disjoint
    assert len(gallery) == len(queries) == 4
    assert {crops[i].identity for i in gallery} == {"a", "b"}


def test_strangers_leave_the_gallery_but_stay_among_queries():
    cows = [f"cow{n}" for n in range(8)]
    crops = _crops({"d1": cows, "d2": cows})

    splits = open_set_splits(crops, strangers_fraction=0.25, folds=3)

    assert len(splits) == 3
    assert len({split.strangers for split in splits}) > 1
    for split in splits:
        assert len(split.strangers) == 2
        assert not split.strangers & {crops[i].identity for i in split.gallery}
        assert split.strangers <= {crops[i].identity for i in split.queries}


def test_no_strangers_is_one_closed_split():
    crops = _crops({"d1": ["a", "b"], "d2": ["a", "b"]})

    (split,) = open_set_splits(crops, strangers_fraction=0)

    assert split.name == "closed"
    assert not split.strangers


def test_rotating_asks_every_session_against_all_the_others():
    cows = [f"cow{n}" for n in range(8)]
    crops = _crops({"d1": cows, "d2": cows, "d3": cows})

    splits = rotating_splits(crops, strangers_fraction=0.25, folds=2)

    assert len(splits) == 6
    asked = [{crops[i].session for i in split.queries} for split in splits]
    assert asked == [{"d1"}, {"d1"}, {"d2"}, {"d2"}, {"d3"}, {"d3"}]
    for split, sessions in zip(splits, asked, strict=True):
        assert not sessions & {crops[i].session for i in split.gallery}
        assert len(split.strangers) == 2
        assert not split.strangers & {crops[i].identity for i in split.gallery}


def test_rotating_needs_two_sessions():
    with pytest.raises(ValueError, match="at least two"):
        rotating_splits(_crops({"d1": ["a", "b"]}))
