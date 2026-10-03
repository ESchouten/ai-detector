from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest
from passage_adaptation import checked_box, yolo_labels
from passage_retention import BurstIdentifier, replay
from passage_torso import associate_torsos, identify_whole_animals

from aidetector.adapters.inference.identity_observations import GalleryIdentifier
from aidetector.domain.models import BoundingBox, IdentityMatch, Observation


def test_native_annotations_produce_distinct_animal_and_torso_classes():
    assert yolo_labels({"boxes": []}, 1920, 1080) == ""
    annotation = {
        "boxes": [{"box": [0, 0, 1920, 1080], "torso_box": [480, 270, 1440, 810]}]
    }
    assert yolo_labels(annotation, 1920, 1080).splitlines() == [
        "0 0.50000000 0.50000000 1.00000000 1.00000000",
        "1 0.50000000 0.50000000 0.50000000 0.50000000",
    ]
    with pytest.raises(ValueError, match="native source"):
        checked_box([0, 0, 1921, 1080], 1920, 1080)


def test_torso_association_rejects_ambiguous_animals_and_duplicate_torsos():
    whole = BoundingBox(0, 0, 200, 200, track_id=7)
    torso = BoundingBox(50, 50, 150, 150, track_id=999)
    assert associate_torsos([whole, whole], [torso]) == []
    assert associate_torsos([whole], [torso, torso]) == []
    assert associate_torsos([whole], [BoundingBox(150, 50, 250, 150)]) == []
    assert associate_torsos([whole], [torso])[0][1].track_id == 7


def test_recognition_sees_torso_but_scoring_retains_whole_geometry_and_unknowns():
    torso = BoundingBox(50, 50, 150, 150, label="coat_torso", track_id=99)
    whole = BoundingBox(0, 0, 200, 200, label="whole_visible_cow", track_id=7)
    unknown = BoundingBox(220, 0, 300, 200, label="whole_visible_cow", track_id=8)
    observation = Observation(
        datetime(2026, 1, 1), np.zeros((300, 400, 3)), {}, (whole, torso, unknown)
    )

    class Identifier:
        def identify(self, source, incoming):
            assert source == "opaque-camera"
            assert incoming.boxes == (replace(torso, label="cow", track_id=7),)
            return replace(
                incoming,
                boxes=(
                    replace(
                        incoming.boxes[0], identity=IdentityMatch("one", "Cow one")
                    ),
                ),
            )

    result = identify_whole_animals(Identifier(), "opaque-camera", observation)
    assert result.boxes[0] == replace(
        whole, label="cow", identity=IdentityMatch("one", "Cow one")
    )
    assert result.boxes[1] == replace(unknown, label="cow", identity=IdentityMatch())


def test_retention_replays_actual_collector_and_bounded_burst_without_inference(
    tmp_path,
):
    import cv2

    image = np.zeros((200, 200, 3), np.uint8)
    cv2.imwrite(str(tmp_path / "frame.png"), image)
    proposals = {"frames": [], "rows": []}
    for index in range(4):
        proposals["frames"].append(
            {
                "clip": "opaque",
                "second": index / 5,
                "rows": [index],
                "path": "frame.png",
            }
        )
        proposals["rows"].append(
            {
                "box": {
                    "x1": 10,
                    "y1": 10,
                    "x2": 150,
                    "y2": 150,
                    "label": "cow",
                    "track_id": 1,
                }
            }
        )
    assert replay(
        tmp_path, proposals, GalleryIdentifier, tmp_path / "normal.sqlite"
    ) == [0]
    assert replay(tmp_path, proposals, BurstIdentifier, tmp_path / "burst.sqlite") == [
        0,
        1,
        2,
    ]
    proposals["frames"].extend(
        [
            {"clip": "opaque", "second": 0.8, "rows": [], "path": "frame.png"},
            {"clip": "opaque", "second": 1.0, "rows": [4], "path": "frame.png"},
        ]
    )
    proposals["rows"].append(proposals["rows"][0])
    assert replay(tmp_path, proposals, GalleryIdentifier, tmp_path / "gap.sqlite") == [
        0,
        4,
    ]
    assert replay(
        tmp_path, proposals, BurstIdentifier, tmp_path / "bounded.sqlite"
    ) == [0, 1, 2]
