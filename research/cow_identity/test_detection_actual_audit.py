"""Named errors without a matching publisher cow still get a review image."""

import numpy as np
from detection_actual_audit import review_absent


def test_absent_named_cow_is_rendered_without_inventing_a_truth_rectangle(
    tmp_path, monkeypatch
):
    source = np.zeros((100, 200, 3), dtype=np.uint8)
    monkeypatch.setattr("detection_actual_audit.read_frame", lambda *_: (201, source))
    rows = [{"second": 10, "seed": 3, "box": [10, 20, 80, 90], "own_truth": None}]
    images = review_absent(None, rows, tmp_path, 20)
    assert len(images) == 1
    assert images[0]["seed"] == 3
    assert images[0]["publisher_frame"] == 201
    assert (tmp_path / images[0]["file"]).is_file()
    assert not source.any()
