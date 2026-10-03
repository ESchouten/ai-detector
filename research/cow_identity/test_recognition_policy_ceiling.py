from recognition_policy_ceiling import assess

from aidetector.configuration import IdentityConfig


def panel(*, overlapping_second=None, track_ids=(1, 1, 1)):
    rows, frames = [], []
    for second, track in enumerate(track_ids):
        indices = [len(rows)]
        rows.append(
            {"box": [10, 10, 110, 110], "confidence": 1, "track": track, "truth": 1}
        )
        if second == overlapping_second:
            indices.append(len(rows))
            rows.append(
                {"box": [20, 20, 120, 120], "confidence": 1, "track": 9, "truth": None}
            )
        frames.append({"second": second, "rows": indices, "truth": [{"cow": 1}]})
    return {"rows": rows, "frames": frames}


def test_perfect_matches_still_require_three_observations_of_same_track():
    settings = IdentityConfig(labels=("cow",))
    continuous = assess(panel(), settings)
    fragmented = assess(panel(track_ids=(1, 2, 3)), settings)
    assert (
        continuous["hard_coverage_ceiling"] == fragmented["hard_coverage_ceiling"] == 1
    )
    assert continuous["counts"]["oracle_confirmed_known"] == 1
    assert fragmented["counts"]["oracle_confirmed_known"] == 0


def test_unmatched_overlapping_box_reduces_eligibility_and_resets_agreement():
    result = assess(panel(overlapping_second=1), IdentityConfig(labels=("cow",)))
    assert result["counts"]["predicted_boxes"] == 4
    assert result["counts"]["visible_known"] == 3
    assert result["counts"]["eligible_known"] == 2
    assert result["counts"]["oracle_confirmed_known"] == 0
