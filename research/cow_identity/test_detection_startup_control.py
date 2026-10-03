import json

import numpy as np
import pytest
from detection_startup_control import initial_masks, prefix_clip


def test_anonymous_initialization_uses_every_survivor_in_input_order(tmp_path):
    masks = np.zeros((3, 10, 30), bool)
    for index in range(3):
        masks[index, 1:9, index * 10 + 1 : index * 10 + 9] = True
    path = tmp_path / "masks.npz"
    np.savez_compressed(path, original=masks)
    proposals = [
        {"x1": i * 10, "y1": 0, "x2": i * 10 + 10, "y2": 10, "confidence": c}
        for i, c in enumerate((0.7, 0.9, 0.8))
    ]
    selected, prompts, decision = initial_masks(
        {"masks": str(path), "proposals": proposals}
    )
    assert np.array_equal(selected, masks)
    assert [p["anonymous_label"] for p in prompts] == ["A", "B", "C"]
    assert [p["proposal_index"] for p in prompts] == [0, 1, 2]
    assert all(p["identity_id"] is None for p in prompts)
    # Frozen reports cross a JSON boundary; relation-map integer keys must not
    # make the same pixel-level selection fail its subsequent replay check.
    assert decision == json.loads(json.dumps(decision))


def test_short_control_requires_every_frozen_half_second():
    rows = [{"second": i / 2, "publisher_frame": i * 10 + 1} for i in range(300)]
    protocol = {"processing_fps": 2, "last_processed_second": 120}
    assert len(prefix_clip({"rows": rows, "source_fps": 20}, protocol)["rows"]) == 241
    with pytest.raises(ValueError, match="timestamps"):
        prefix_clip({"rows": rows[:240], "source_fps": 20}, protocol)
