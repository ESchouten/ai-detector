"""Guard mask topology, fixed object slots and calibration selection rules."""

import numpy as np
from detection_cutie import boxes_from_mask
from detection_cutie_variants import choose, largest_components, probability_gate

from aidetector.domain.models import BoundingBox


def test_largest_component_uses_eight_neighbors_and_row_major_area_ties():
    mask = np.zeros((12, 12), dtype=np.uint8)
    mask[1:3, 1:3] = 1
    mask[6:8, 6:8] = 1
    mask[8, 1] = 3
    mask[9, 2] = 3
    mask[11, 10] = 3
    original = mask.copy()
    cleaned, statistics = largest_components(mask)
    assert np.array_equal(mask, original)
    assert cleaned[1, 1] == 1 and cleaned[6, 6] == 0
    assert cleaned[8, 1] == 3 and cleaned[9, 2] == 3
    assert cleaned[11, 10] == 0
    assert [box["track_id"] for box in boxes_from_mask(cleaned)] == [0, 2]
    assert [row["retained_area"] for row in statistics] == [4, 2]


def test_confidence_gate_is_inclusive_and_does_not_use_another_objects_score():
    frame = {
        "objects": [
            {"track_id": 0, "p10_probability": 0.7},
            {"track_id": 2, "p10_probability": 0.95},
        ]
    }
    box = BoundingBox(0, 0, 10, 10, track_id=0)
    assert probability_gate(0.7)(frame, box)
    assert not probability_gate(0.8)(frame, box)


def test_selection_rejects_inaccurate_coverage_and_breaks_ties_by_simple_rule():
    def result(variant, threshold, coverage, precision, unknown=0):
        return {
            "box_variant": variant,
            "minimum_p10_probability": threshold,
            "unknown_false_naming_rate": unknown,
            "metrics": {
                "known_coverage": coverage,
                "conservative_precision": precision,
            },
        }

    simple = result("raw", 0.5, 0.8, 0.995)
    variants = [
        result("raw", 0, 0.98, 0.97),
        result("raw", 0, 0.9, 0.999, 0.02),
        result("largest_8_connected_component", 0, 0.8, 0.995),
        result("raw", 0.7, 0.8, 0.995),
        simple,
    ]
    assert choose(variants, 0.6) == {"selected": simple, "meets_all_gates": True}
    assert not choose([result("raw", 0, 0.2, 1)], 0.6)["meets_all_gates"]
    assert choose(variants[:2], 0.6)["selected"] is None
