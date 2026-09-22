import pytest

from aidetector.domain.models import BoundingBox


@pytest.mark.parametrize(
    "boxes, expected",
    [
        ((), None),
        ((BoundingBox(10, 20, 30, 40, "cow", 0.9),), BoundingBox(10, 20, 30, 40)),
        (
            (
                BoundingBox(10, 20, 30, 40, "cow", 0.9),
                BoundingBox(50, 5, 80, 70, "horse", 0.8),
                BoundingBox(-5, 30, 12, 60),
            ),
            BoundingBox(-5, 5, 80, 70),
        ),
    ],
)
def test_enclosing_region_covers_every_box_without_a_class_label(boxes, expected):
    assert BoundingBox.enclosing(boxes) == expected
