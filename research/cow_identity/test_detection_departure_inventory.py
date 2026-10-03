from detection_departure_inventory import absent_runs
from detection_retirement_burden import longest_visible_gap


def rows(seconds, present=()):
    return [
        {"second": t, "absent": t not in present, "truth": "annotated"} for t in seconds
    ]


def test_retirement_requires_five_elapsed_seconds_not_ten_samples():
    assert (
        absent_runs(rows([i / 2 for i in range(10)]), "absent")[0][
            "five_second_trigger"
        ]
        is None
    )
    assert (
        absent_runs(rows([i / 2 for i in range(11)]), "absent")[0][
            "five_second_trigger"
        ]
        == 5.0
    )


def test_capture_gap_does_not_count_as_observed_absence():
    result = absent_runs(rows([0, 0.5, 10, 10.5]), "absent")
    assert [r["observed_span_seconds"] for r in result] == [0.5, 0.5]
    assert all(r["five_second_trigger"] is None for r in result)


def test_any_foreground_resets_timer_and_final_short_gap_is_censored():
    result = absent_runs(rows([i / 2 for i in range(15)], present={3}), "absent")
    assert [(r["start"], r["end"]) for r in result] == [(0, 2.5), (3.5, 7)]
    assert [r["right_censored"] for r in result] == [False, True]
    assert all(r["five_second_trigger"] is None for r in result)


def test_missing_truth_breaks_observed_naming_gap_without_imputing_absence():
    observations = [
        {"second": second, "present": second != 2, "named": second == 0}
        for second in range(6)
    ]
    assert longest_visible_gap(observations, "named") == {
        "start": 3,
        "end": 5,
        "samples_1hz": 3,
        "observed_span_seconds": 2,
        "right_censored": True,
    }
