"""Reference questions must be selected without labels or future outcomes."""

from recognition_masked_pilot import candidates, eligible, pilot


def frame(second, **changes):
    return {
        "second": second,
        "source_pixels_sha256": "pixels",
        "mask_sha256": "mask",
        "conflicted_ids": [],
        "reciprocal_pairs": [{"track_id": 0}],
        "objects": [{"track_id": 0, "area": 6000, "p10_probability": 0.8}],
        "boxes": [{"track_id": 0, "x1": 10, "y1": 10, "x2": 110, "y2": 110}],
        **changes,
    }


def test_quality_and_ranking_precede_first_last_pilot_selection():
    rows = [frame(i) for i in range(630)]
    rows[320]["objects"][0]["p10_probability"] = 0.9
    rows[321]["objects"][0].update(p10_probability=0.9, area=7000)
    rows[322]["objects"][0].update(p10_probability=0.9, area=7000)
    rows[575]["objects"][0]["p10_probability"] = 0.99
    rows[575]["conflicted_ids"] = [1]
    rows[576]["objects"][0]["p10_probability"] = 0.99
    rows[576]["reciprocal_pairs"] = []
    winners = candidates(rows)
    assert len(winners) == 10
    assert [r["second"] for r in pilot(winners)] == [321, 567]


def test_missing_bins_do_not_force_or_backfill_questions():
    rows = [frame(i, boxes=[]) for i in range(630)]
    rows[400] = frame(400)
    rows[410] = frame(410)
    rows[410]["boxes"][0]["x1"] = 0
    winners = candidates(rows)
    assert [r["second"] for r in pilot(winners)] == [400]
    rows[400]["objects"][0]["p10_probability"] = 0.69
    assert pilot(candidates(rows)) == []


def test_recorded_conflicts_are_stable_one_based_object_ids():
    row = frame(0, conflicted_ids=[1])
    stats = {0: row["objects"][0]}
    assert not eligible(row, row["boxes"][0], stats)
    row["conflicted_ids"] = [2]
    assert eligible(row, row["boxes"][0], stats)
