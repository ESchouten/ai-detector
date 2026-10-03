import json

import eartag_localization_tiles as subject
import pytest


@pytest.mark.parametrize("size", (1, 1279, 1280, 1281, 1800, 4000, 4133))
def test_edge_anchored_tiles_cover_source_without_extra_resize(size):
    starts = subject.origins(size)
    assert starts[0] == 0 and starts[-1] + min(size, 1280) == size
    assert len(starts) == len(set(starts))
    assert all(0 < b - a <= 1024 for a, b in zip(starts, starts[1:], strict=False))
    rectangles = subject.tiles((size, 2071, 3))
    assert all(
        0 <= x < right <= 2071 and 0 <= y < bottom <= size
        for x, y, right, bottom in rectangles
    )
    assert rectangles[-1][2:] == [2071, size]


def test_native_offsets_and_library_nms_preserve_classes_and_extra_detections():
    tag = {"class": 1, "confidence": 0.8, "xyxy": [0, 5, 100, 105]}
    shifted = subject.shifted(tag, [1024, 520, 2304, 1800])
    assert shifted["xyxy"] == [1024, 525, 1124, 625]
    rows = [shifted, {**shifted, "confidence": 0.7}, {**shifted, "class": 0}]
    rows.extend(
        {"class": 1, "confidence": 0.6, "xyxy": [i * 5, 0, i * 5 + 2, 2]}
        for i in range(301)
    )
    merged, keep = subject.merge(rows)
    assert keep[:2] == [0, 2]
    assert len(merged) == 303  # No global300cap; all separated extras retained.
    assert subject.merge([]) == ([], [])


def test_single_tile_lowres_postmerge_parity_is_fail_closed_before_truth(
    tmp_path, monkeypatch
):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("{}")
    protocol, output = tmp_path / "protocol.json", tmp_path / "score.json"
    protocol.write_text("{}")
    monkeypatch.setattr(subject, "checked", lambda _: {})
    monkeypatch.setattr(subject, "validate_tiles", lambda *_: False)

    def truth_not_allowed(*_):
        raise AssertionError("Truth must not be accessed after failed parity")

    monkeypatch.setattr(subject, "scored", truth_not_allowed)
    subject.score(protocol, raw_path, output)
    assert json.loads(output.read_text())["status"] == "FAILED_LOWRES_PARITY"
    assert json.loads(output.read_text())["scores"] is None
