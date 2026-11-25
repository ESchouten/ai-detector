import numpy as np
import pytest

from aidetector.adapters.individuals.tags import HEIGHT_MIN, TagReader
from tests.support.onnx_model import write_tag_models

WHITE, GREY = (255, 255, 255), (190, 190, 190)


def picture(tag, colour=WHITE, width=90, height=90):
    """A red individual with a tag at (x1, y1, x2, y2)."""
    image = np.full((height, width, 3), (0, 0, 255), np.uint8)
    x1, y1, x2, y2 = tag
    image[y1:y2, x1:x2] = colour
    return image


def test_a_tags_number_is_read_where_the_tag_is_found(tmp_path):
    reader = TagReader(*write_tag_models(tmp_path))

    [tag] = reader.read(picture((20, 30, 50, 80)))

    assert tag.box == (20, 30, 50, 80)
    assert (tag.text, tag.confidence) == ("5359", pytest.approx(1, abs=0.02))
    # Its pixels come with a margin, so a tilted tag is whole.
    assert tag.crop.shape[:2] == (50 + 2 * 8, 30 + 2 * 4)
    assert (tag.crop[25, 15] == WHITE).all()


def test_the_reader_is_less_sure_of_a_number_it_can_hardly_read(tmp_path):
    reader = TagReader(*write_tag_models(tmp_path))

    [tag] = reader.read(picture((20, 30, 50, 80), GREY))

    assert tag.text == "5359"
    assert 0.5 < tag.confidence < 0.9


def test_a_picture_larger_than_the_finder_takes_is_shrunk_to_fit(tmp_path):
    reader = TagReader(*write_tag_models(tmp_path))

    [tag] = reader.read(picture((40, 60, 100, 160), width=540, height=576))

    assert tag.box == (40, 60, 100, 160)
    assert tag.text == "5359"


def test_tags_too_small_to_read_and_pictures_without_a_tag_give_nothing(tmp_path):
    reader = TagReader(*write_tag_models(tmp_path))

    assert reader.read(picture((20, 30, 50, 30 + HEIGHT_MIN - 1))) == []
    assert reader.read(picture((0, 0, 0, 0))) == []


def test_a_reader_without_a_charset_is_refused(tmp_path):
    finder, lines, _ = write_tag_models(tmp_path)

    with pytest.raises(ValueError, match="charset"):
        TagReader(finder, lines, lines)
