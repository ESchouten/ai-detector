from ethz import DISPUTED, confirmed_before, crop_time, development_rows, frame_labels


def row(cow, date, time):
    return {"cow": cow, "date": date, "time": time}


ROWS = [
    row(1, "20230823", "120000"),
    row(1, "20230824", "144855"),  # exactly a day before video3 starts
    row(1, "20230824", "144856"),
    row(1, "20230825", "150000"),  # inside video3
    row(1, "20230830", "120000"),  # days after video3 and every held-back video
    row(2, "20230823", "120000"),
]


def test_only_photographs_a_day_older_teach_the_evaluated_model():
    chosen = confirmed_before(ROWS, "video3", {1})
    assert [crop_time(item).isoformat() for item in chosen] == [
        "2023-08-23T12:00:00",
        "2023-08-24T14:48:55",
    ]


def test_development_may_also_use_photographs_a_day_after_the_video():
    chosen = confirmed_before(ROWS, "video3", {1}, either_side=True)
    assert [crop_time(item).isoformat() for item in chosen] == [
        "2023-08-23T12:00:00",
        "2023-08-24T14:48:55",
        "2023-08-30T12:00:00",
    ]


def test_animals_outside_the_enrolled_set_are_left_out():
    assert all(item["cow"] == 1 for item in confirmed_before(ROWS, "video3", {1}))


def test_development_stays_a_day_away_from_held_back_videos():
    rows = [
        row(1, "20230823", "120000"),
        row(1, "20230826", "100000"),  # within a day of video2 and video1
        row(1, "20230828", "011000"),  # minutes before video6
        row(1, "20230830", "120000"),
        row(1, "20230916", "140000"),  # within a day of video5
    ]
    assert [item["date"] for item in development_rows(rows)] == ["20230823", "20230830"]
    assert [item["date"] for item in confirmed_before(rows, "video3", {1}, either_side=True)] == [
        "20230823",
        "20230830",
    ]


def test_a_cow_boxed_twice_in_one_frame_is_disputed(tmp_path):
    labels = tmp_path / "video9" / "labels"
    labels.mkdir(parents=True)
    (labels / "frame_000007.txt").write_text(
        "11 0.25 0.5 0.1 0.2\n11 0.75 0.5 0.1 0.2\n4 0.5 0.5 0.2 0.2\n"
    )
    boxes = frame_labels(tmp_path, "video9", 7, 100, 50)
    assert [box[0] for box in boxes] == [DISPUTED, DISPUTED, 4]
    assert boxes[2][1:] == (40.0, 20.0, 60.0, 30.0)
