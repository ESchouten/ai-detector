from recognition_spatial_tail_data import all_six_groups, training_schedule
from recognition_temporal_features import positive_groups


def test_all_six_extension_preserves_original_four_animal_pair_rule():
    rows = [
        {"track_id": track, "second": second, "run_start": 0}
        for track in range(4)
        for second in (0, 10, 20, 30, 40)
    ]
    assert all_six_groups(rows) == positive_groups(rows)


def test_fixed_schedule_only_sameframe_known_early_pairs_with_at_most_eight_crops():
    rows = [
        {"kind": "observation", "track_id": track, "second": second, "run_start": 0}
        for second in (0, 20, 40, 420, 450)
        for track in range(8)
    ]
    groups = all_six_groups(rows)
    schedule = training_schedule(groups, {"rows": rows})
    assert len(schedule) == 200
    assert schedule == training_schedule(groups, {"rows": rows})
    for step in schedule:
        assert 4 <= len(step["source_indices"]) <= 8
        assert all(
            rows[i]["track_id"] < 6 and rows[i]["second"] <= 419
            for i in step["source_indices"]
        )
        assert len({p["anchor_second"] for p in step["pairs"]}) == 1
        assert len({p["track_id"] for p in step["pairs"]}) == len(step["pairs"])
