"""A denser inference sequence must not silently change scored time or seeds."""

from copy import deepcopy

import pytest
from detection_cutie_cadence import validate_timeline


def inputs():
    protocol = {
        "processing_fps": 5,
        "last_processed_second": 2,
        "clip_plan_sha256": "frozen-plan",
        "comparison_windows": [[1, 2]],
        "seeded_cows": [1, 8],
        "quality_control": {
            "thresholds": [0.7],
            "box_variants": ["largest_8_connected_component"],
        },
    }
    clip = {
        "contract": {"protocol_sha256": "frozen-plan"},
        "source_fps": 20,
        "rows": [
            {"second": index / 5, "publisher_frame": index * 4 + 1}
            for index in range(11)
        ],
    }
    value = {
        "complete": True,
        "stop_reason": None,
        "frame_seconds": [0.1] * 11,
        "timeline": [{"second": second} for second in range(3)],
        "provenance": {"seed_prompts": [{"cow": 1}, {"cow": 8}]},
    }
    rules = {
        "processed_seconds": [0, 2],
        "score_windows": {"comparison": [1, 2]},
        "base": {
            "minimum_p10_probability": 0.7,
            "box_variant": "largest_8_connected_component",
        },
    }
    return value, protocol, clip, rules


def test_denominator_uses_every_integer_second_despite_denser_inference():
    value, protocol, clip, rules = inputs()
    validate_timeline(value, protocol, clip, rules)
    value["timeline"].pop(1)
    with pytest.raises(ValueError, match="every integer second"):
        validate_timeline(value, protocol, clip, rules)


def test_source_frame_offset_or_missing_fractional_frame_is_rejected():
    original, protocol, clip, rules = inputs()
    shifted = deepcopy(clip)
    shifted["rows"][2]["publisher_frame"] -= 1
    with pytest.raises(ValueError, match="source cadence"):
        validate_timeline(original, protocol, shifted, rules)
    clip["rows"].pop(2)
    with pytest.raises(ValueError, match="source cadence"):
        validate_timeline(original, protocol, clip, rules)


def test_seed_permutation_cannot_be_scored_as_the_frozen_identity_mapping():
    value, protocol, clip, rules = inputs()
    value["provenance"]["seed_prompts"].reverse()
    with pytest.raises(ValueError, match="scoring policy"):
        validate_timeline(value, protocol, clip, rules)
