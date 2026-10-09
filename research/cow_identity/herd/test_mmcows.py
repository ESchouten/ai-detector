from datetime import datetime

import ethz
import mmcows


def test_file_names_carry_the_second_and_the_barn_is_five_hours_behind():
    assert mmcows.stamp("visual_data/images/0725/cam_1/1690308011_13-00-11.jpg") == 1690308011
    assert mmcows.barn_time(1690308011) == datetime(2023, 7, 25, 13, 0, 11)
    assert mmcows.seconds_at("13:00") == 1690308000


def test_a_video_is_one_camera_from_an_hour_on_of_the_annotated_day():
    first, last = mmcows.window("mmcows-1400-cam3")

    assert mmcows.barn_time(first) == datetime(2023, 7, 25, 14)
    assert last - first == 3600
    assert mmcows.window("mmcows-1200-cam1")[1] - mmcows.window("mmcows-1200-cam1")[0] == 1800
    assert mmcows.barn_time(mmcows.window("mmcows-2200-cam4")[1]) == datetime(2023, 7, 25, 23)
    assert len(mmcows.VIDEOS) == 16


def test_every_fourth_cow_stays_unknown():
    assert not set(mmcows.ENROLLED) & set(mmcows.WITHHELD)
    assert sorted(mmcows.ENROLLED + mmcows.WITHHELD) == list(range(1, 17))


def test_photographs_must_be_four_hours_older_than_a_video_of_this_farm():
    rows = [{"cow": 1, "date": "20230725", "time": time} for time in ("075900", "080100", "100000")]

    assert len(ethz.confirmed_before(rows, "mmcows-1200-cam1", {1})) == 1
    assert len(ethz.confirmed_before(rows, "mmcows-1400-cam1", {1})) == 3
    # A video of the ETH barn still asks for a whole day.
    assert (
        ethz.confirmed_before([{"cow": 0, "date": "20230827", "time": "120000"}], "video1", {0})
        == []
    )


def test_the_photographs_end_four_hours_before_the_first_video():
    first_video = min(mmcows.window(video)[0] for video in mmcows.VIDEOS)

    assert first_video - mmcows.seconds_at(mmcows.PHOTOGRAPHS[1]) == mmcows.GAP_HOURS * 3600


def test_publisher_lines_are_a_cow_and_her_box():
    assert mmcows.boxes("9 0.5 0.25 0.2 0.1\n14 0.7 0.3 0.05 0.13\n") == [
        (9, 0.5, 0.25, 0.2, 0.1),
        (14, 0.7, 0.3, 0.05, 0.13),
    ]
