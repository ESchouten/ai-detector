import numpy as np
import pytest

from reid.tracking import Detection, covered, cut, usable

pytest.importorskip("cv2")


def test_covered_counts_overlapping_neighbours_once():
    box = Detection(1, 0, 0, 10, 10)
    left = Detection(2, -5, 0, 5, 10)
    also_left = Detection(3, -5, 0, 5, 5)

    assert covered(box, [box]) == 0
    assert covered(box, [box, left, also_left]) == pytest.approx(0.5)


def test_usable_needs_size_room_from_the_edge_and_little_cover():
    box = Detection(1, 100, 100, 300, 300)
    big_neighbour = Detection(2, 150, 100, 400, 300)

    assert usable(box, [box], 640, 480, min_size=128, max_covered=0.3)
    assert not usable(box, [box], 640, 480, min_size=256, max_covered=0.3)
    assert not usable(
        box, [box, big_neighbour], 640, 480, min_size=128, max_covered=0.3
    )
    edge = Detection(3, 0, 100, 200, 300)
    assert not usable(edge, [edge], 640, 480, min_size=128, max_covered=0.3)


def test_cut_grays_out_everything_outside_the_outline():
    image = np.full((50, 50, 3), 200, np.uint8)
    outline = np.array([[10, 10], [30, 10], [30, 30], [10, 30]], np.float32)
    detection = Detection(1, 10, 10, 40, 40, outline)

    masked = cut(image, detection, mask_background=True)
    plain = cut(image, detection, mask_background=False)

    assert masked.shape == plain.shape == (30, 30, 3)
    assert (masked[5, 5] == 200).all()
    assert (masked[25, 25] == 127).all()
    assert (plain == 200).all()
