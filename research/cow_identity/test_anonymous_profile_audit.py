import pytest
from anonymous_profile_audit import evidence_summary, summarize


def test_unmatched_evidence_is_not_reported_as_pure():
    summary = evidence_summary([{"cow": 2}, {"cow": 2}, {"cow": None}])
    assert summary["dominant_matched_fraction"] == 1
    assert summary["dominant_fraction_including_unmatched"] == 2 / 3
    assert not summary["fully_matched_single_animal"]
    assert not summary["mixed_animals"]


def test_clean_retained_photo_does_not_hide_earlier_episode_switch():
    candidate = {
        "profile_id": "profile",
        "episode_id": "episode",
        "recorded_slot": 0,
        "second": 2,
        "publisher_frame": 41,
        "box": [10, 20, 110, 120],
    }
    inventory = {
        "episodes": [
            {
                "profile_id": "profile",
                "episode_id": "episode",
                "recorded_slot": 0,
                "first_second": 0,
                "last_second": 2,
                "qualified_observations": 3,
            }
        ],
        "candidate_observations": [candidate],
        "retained_candidates": [candidate],
    }
    matches = {
        (second, 0): {
            "cow": cow,
            "publisher_frame": second * 20 + 1,
            "box": [10, 20, 110, 120],
        }
        for second, cow in enumerate([1, 2, 2])
    }
    result = summarize(inventory, matches)
    assert result["totals"]["mixed_episodes"] == 1
    assert (
        result["candidates"]["retained_candidates"]["summary"]["from_mixed_episode"]
        == 1
    )
    assert result["episodes"][0]["dominant_fraction_including_unmatched"] == 2 / 3
    matches[3, 0] = matches[2, 0]
    with pytest.raises(ValueError, match="Every qualified observation"):
        summarize(inventory, matches)


def test_different_animals_between_episodes_are_not_merged_by_the_audit():
    inventory = {
        "episodes": [
            {
                "profile_id": "slot",
                "episode_id": str(i),
                "recorded_slot": 0,
                "first_second": i,
                "last_second": i,
                "qualified_observations": 1,
            }
            for i in range(2)
        ],
        "candidate_observations": [],
        "retained_candidates": [],
    }
    result = summarize(inventory, {(0, 0): {"cow": 1}, (1, 0): {"cow": 2}})
    assert result["totals"]["mixed_episodes"] == 0
    assert result["profiles"][0]["mixed_animals"]
