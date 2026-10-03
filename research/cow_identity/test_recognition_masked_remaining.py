"""Remaining review must not silently resample rejected or initial questions."""

from recognition_masked_review_remaining import remaining


def test_remaining_excludes_initial_and_pilot_without_replacement():
    rows = [
        {"track_id": track, "second": second}
        for track in range(6)
        for second in (0, 63, 126)
    ]
    selection = {"winners": rows, "pilot": [r for r in rows if r["second"] == 126]}
    actual = remaining(selection)
    assert {(r["track_id"], r["second"]) for r in actual} == {
        (track, 63) for track in range(6)
    }
    assert [r["candidate"] for r in actual] == list(range(12, 18))
    assert all("candidate" not in row for row in rows)
    assert remaining(selection) == actual
