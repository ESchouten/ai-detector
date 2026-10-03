from anonymous_profile_inventory import inventory


def frames():
    return [
        {
            "second": i,
            "publisher_frame": 20 * i + 1,
            "boxes": [
                {"track_id": t, "x1": 10, "y1": 10, "x2": 110 + i, "y2": 130}
                for t in (0, 7)
            ],
            "objects": [
                {"track_id": t, "p10_probability": 0.9, "area": 10000} for t in (0, 7)
            ],
            "reciprocal_pairs": [{"track_id": t} for t in (0, 7)],
            "conflicted_ids": [],
            "source_pixels_sha256": "pixels",
            "mask_sha256": "mask",
        }
        for i in range(200)
    ]


def test_all_slots_labels_irrelevant_and_reservoir_bounded():
    source = frames()
    context = {"run_id": "run", "source_key": "source", "epoch": "epoch"}
    plain = inventory(source, context, 800, 600)
    for frame in source:
        frame["named_track_ids"] = [7]
        frame["truth"] = {0: 999, 7: 1}
    assert inventory(source, context, 800, 600) == plain
    assert plain["counts"]["retained_per_slot"] == {0: 16, 7: 16}
    assert plain["candidate_observations"][0]["second"] == 2


def test_quality_gap_breaks_episode_and_does_not_create_biological_link():
    source = frames()[:20]
    source[5]["conflicted_ids"] = [1]
    result = inventory(
        source, {"run_id": "run", "source_key": "source", "epoch": "epoch"}, 800, 600
    )
    first = [e for e in result["episodes"] if e["recorded_slot"] == 0]
    assert [(e["first_second"], e["last_second"]) for e in first] == [(0, 4), (6, 19)]
    assert first[0]["episode_id"] != first[1]["episode_id"]
    assert first[0]["profile_id"] == first[1]["profile_id"]
    assert all(
        p["status"] == "anonymous_observation_instance_not_biological_identity"
        for p in result["profiles"]
    )
