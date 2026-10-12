import json

import numpy as np
import pytest

import mootrack


def test_the_middle_of_a_picture_is_straight_down_and_its_rim_is_level():
    middle = mootrack.SIDE / 2
    rim = middle + 2 * mootrack.FOCAL

    assert mootrack.off_axis([middle - 50, middle - 80, middle + 50, middle + 80]) == 0
    assert mootrack.off_axis([rim - 10, middle - 10, rim + 10, middle + 10]) == pytest.approx(90)


def test_the_barn_is_upright_above_the_middle_and_on_its_head_below_it():
    middle = mootrack.SIDE / 2

    assert mootrack.turned([middle - 10, 100, middle + 10, 300]) == 0
    assert mootrack.turned([middle - 10, 2600, middle + 10, 2800]) == 180
    assert mootrack.turned([100, middle - 10, 300, middle + 10]) == 90
    assert mootrack.turned([2600, middle - 10, 2800, middle + 10]) == 90


def test_a_box_turns_with_its_picture():
    box = [100, 200, 300, 250]
    picture = np.zeros((mootrack.SIDE, mootrack.SIDE), dtype=bool)
    picture[200:250, 100:300] = True

    for turns in range(5):
        rows, columns = np.nonzero(np.rot90(picture, turns))

        assert mootrack.quarter(box, turns) == [
            columns.min(),
            rows.min(),
            columns.max() + 1,
            rows.max() + 1,
        ]


def test_a_cow_is_upright_in_one_turn_on_her_head_in_one_and_on_her_side_in_two():
    box = [1400, 300, 1500, 500]

    turns = sorted(mootrack.turned(mootrack.quarter(box, turns)) // 45 for turns in range(4))

    assert turns == [0, 1, 2, 3]
    assert (
        len({round(mootrack.off_axis(mootrack.quarter(box, turns)), 6) for turns in range(4)}) == 1
    )


def test_a_picture_carries_its_camera_its_day_and_its_cows_in_pixels(tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "id": 7,
                        "file_name": "Kamera20119_frame_0.jpg",
                        "coco_url": "AmlDatastore://still_images/02/2024_08_22_2024_09_12/"
                        "0002D1A4B8B7/20241124/07/Kamera20119.mp4/Kamera20119_frame_0.jpg",
                    },
                    {
                        "id": 8,
                        "file_name": "not_fetched.jpg",
                        "coco_url": "AmlDatastore://still_images/03/kamera_12/"
                        "0002D1AA8CFB/20241224/not_fetched.jpg",
                    },
                ],
                "annotations": [
                    {"image_id": 7, "category_id": 3, "bbox": [0.25, 0.5, 0.125, 0.0625]},
                    {"image_id": 7, "category_id": 2, "bbox": [0.0, 0.0, 0.5, 0.5]},
                ],
            }
        )
    )
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    (pictures / "7_Kamera20119_frame_0.jpg").touch()

    (picture,) = mootrack.pictures(labels, pictures)

    assert (picture["camera"], picture["day"]) == ("0002D1A4B8B7", "20241124")
    assert picture["cows"] == [
        {"posture": "lying", "box": [736.0, 1472.0, 1104.0, 1656.0]},
        {"posture": "standing", "box": [0.0, 0.0, 1472.0, 1472.0]},
    ]


def test_nine_windows_cover_a_picture_and_the_whole_view_is_one():
    assert mootrack.windows("whole") == [(0, 0, mootrack.SIDE)]

    parts = mootrack.windows("near")

    assert len(parts) == 9
    assert parts[0] == (0, 0, 1280)
    assert parts[4] == (832, 832, 1280)
    assert parts[8] == (1664, 1664, 1280)


def test_a_cow_is_counted_in_the_window_that_has_her_nearest_its_middle():
    parts = mootrack.windows("near")

    # Whole inside the first two windows of the top row; nearer the middle of the second.
    assert mootrack.window_of([1100, 100, 1270, 300], parts) == 1
    assert mootrack.window_of([10, 10, 300, 200], parts) == 0


def test_a_cow_that_no_window_holds_whole_is_counted_in_none():
    assert mootrack.window_of([100, 100, 1500, 300], mootrack.windows("near")) is None


def cow(posture, found, fit, off_axis=10.0, longer_side=150.0, infrared=False, turned=0.0):
    return {
        "turned": turned,
        "camera": "0002D1A4B8B7",
        "day": "20241124",
        "posture": posture,
        "found": found,
        "fit": fit,
        "off_axis": off_axis,
        "longer_side": longer_side,
        "infrared": infrared,
        "overlap": 0.8 if found else 0.1,
    }


def test_cows_are_counted_with_the_shares_found_and_fit():
    cows = [cow("lying", True, True), cow("lying", True, False), cow("lying", False, False)]

    assert mootrack.counted(cows) == {"cows": 3, "found": 2 / 3, "fit": 1 / 3}
    assert mootrack.counted([]) == {"cows": 0}


def test_cows_are_counted_by_the_range_a_measure_falls_in():
    cows = [cow("lying", True, True, off_axis=5), cow("lying", False, False, off_axis=20)]

    by_angle = mootrack.between(cows, "off_axis", (0, 20, 40))

    assert by_angle["0-20"] == {"cows": 1, "found": 1.0, "fit": 1.0}
    assert by_angle["20-40"] == {"cows": 1, "found": 0.0, "fit": 0.0}


def test_cows_to_one_side_are_counted_by_how_far_the_barn_is_turned():
    cows = [
        cow("standing", True, True, off_axis=50, turned=10),
        cow("standing", False, False, off_axis=50, turned=170),
        cow("standing", True, True, off_axis=10, turned=170),
    ]

    sideways = mootrack.summarised(cows)["standing"]["by_degrees_off_straight_down_and_turned"]

    assert sideways["40-60"]["0-45"] == {"cows": 1, "found": 1.0, "fit": 1.0}
    assert sideways["40-60"]["135-181"] == {"cows": 1, "found": 0.0, "fit": 0.0}
    assert sideways["60-90"]["0-45"] == {"cows": 0}


def test_a_view_is_summarised_by_posture_light_and_barn():
    cows = [
        cow("lying", True, True),
        cow("lying", False, False, infrared=True),
        cow("standing", True, True),
    ]

    result = mootrack.summarised(cows)

    assert (result["cows"], result["found"]) == (3, 2 / 3)
    assert result["median_overlap_of_the_found"] == 0.8
    assert result["lying"]["found"] == 0.5
    assert result["lying"]["by_light"]["infrared"] == {"cows": 1, "found": 0.0, "fit": 0.0}
    assert result["standing"]["by_barn"] == {
        "barn with four cameras": {"cows": 1, "found": 1.0, "fit": 1.0},
        "barn with twelve cameras": {"cows": 0},
    }
