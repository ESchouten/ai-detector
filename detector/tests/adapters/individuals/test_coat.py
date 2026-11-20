import numpy as np

from aidetector.adapters.individuals.coat import CoatModel
from tests.support.onnx_model import CELLS, write_coat_models

RED, GREEN = (0, 0, 255), (0, 255, 0)


def picture(left, right, width=60, height=60):
    image = np.full((height, width, 3), left, np.uint8)
    image[:, width // 2 :] = right
    return image


def test_the_coat_details_two_pictures_share_are_counted(tmp_path):
    model = CoatModel(*write_coat_models(tmp_path))
    spotted = model.describe(picture(RED, GREEN))

    assert model.shared(spotted, model.describe(picture(RED, GREEN))) == CELLS**2
    # Only her red half shows in a picture of a red coat, and nothing of
    # either half in one with the halves the other way round.
    assert model.shared(spotted, model.describe(picture(RED, RED))) == CELLS**2 // 2
    assert model.shared(spotted, model.describe(picture(GREEN, RED))) == 0


def test_pictures_are_scaled_to_the_longer_side_the_keypoints_model_names(tmp_path):
    usual = CoatModel(*write_coat_models(tmp_path))
    assert usual.describe(picture(RED, GREEN, 120, 60)).size.tolist() == [[512, 256]]

    small = CoatModel(*write_coat_models(tmp_path, {"size": "64"}))
    assert small.describe(picture(RED, GREEN, 120, 60)).size.tolist() == [[64, 32]]
    # No side becomes too small to find keypoints in.
    assert small.describe(picture(RED, GREEN, 400, 20)).size.tolist() == [[64, 32]]
