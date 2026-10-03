from cutie_geometry import padded_box


def test_uniform_margin_retains_identity_and_clips_to_frame():
    box = dict(x1=0, y1=10, x2=100, y2=110, track_id=4, confidence=1.0, label="cow")
    result = padded_box(box, 1.2, 105, 200)
    assert [result[key] for key in ("x1", "y1", "x2", "y2")] == [0, 0, 105, 120]
    assert result["track_id"] == box["track_id"]
    assert box["x2"] == 100


def test_unpadded_control_preserves_coordinates_exactly():
    box = dict(x1=12, y1=14, x2=81, y2=171, track_id=0, confidence=1.0, label="cow")
    assert padded_box(box, 1, 100, 200) == box
