import numpy as np
from cutie_features import object_crops


def test_foreground_crops_keep_original_slots_and_remove_other_cows():
    image = np.full((20, 20, 3), 200, dtype=np.uint8)
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[2:15, 2:15] = 2
    mask[5:9, 5:9] = 7
    mask[18, 18] = 2  # A disconnected island must not expand the crop.
    boxes, crops, components = object_crops(image, mask)
    assert [box["track_id"] for box in boxes] == [1, 6]
    assert (boxes[0]["x1"], boxes[0]["x2"]) == (2, 14)
    assert np.all(crops[0][3:7, 3:7] == 127)
    assert np.all(crops[1] == 200)
    assert components[0]["component_count"] == 2


def test_empty_mask_emits_no_synthetic_observation():
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    assert object_crops(image, image[:, :, 0]) == ([], [], [])
