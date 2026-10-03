"""A detector veto is geometric evidence; calibration cannot forgive low precision."""

from detection_corroboration import choose, maximum_iou


def test_empty_detector_frame_cannot_corroborate_and_half_overlap_is_exact():
    whole = {"x1": 0, "y1": 0, "x2": 20, "y2": 10}
    half = {**whole, "x2": 10}
    assert maximum_iou(whole, []) == 0
    assert maximum_iou(whole, [half]) == 0.5
    assert maximum_iou(whole, [half, whole]) == 1


def test_calibration_selects_coverage_only_after_precision_and_unknown_constraints():
    def condition(threshold, coverage, precision, unknown=0):
        return {
            "minimum_iou": threshold,
            "unknown_false_naming_rate": unknown,
            "metrics": {
                "known_coverage": coverage,
                "conservative_precision": precision,
            },
        }

    bad_precision = condition(None, 0.95, 0.98)
    better = condition(0.5, 0.75, 0.99)
    strict = condition(0.7, 0.60, 1)
    assert choose([bad_precision, better, strict]) == better
    assert choose([condition(0.5, 0.9, 1, 0.02)]) is None
    baseline = condition(None, 0.75, 0.99)
    assert choose([better, baseline]) == baseline
