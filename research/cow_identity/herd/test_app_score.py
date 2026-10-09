import json

from app_score import labelled_frames


def index(tmp_path, frames):
    (tmp_path / "frames.json").write_text(json.dumps({"frames": frames}))
    return tmp_path


def test_every_frame_of_a_fully_boxed_video_is_judged(tmp_path):
    assert labelled_frames(index(tmp_path, [{"index": 0}, {"index": 15}])) == [0, 15]


def test_frames_the_publisher_did_not_box_are_left_out(tmp_path):
    frames = [
        {"index": 100, "labelled": False},
        {"index": 101, "labelled": True},
        {"index": 102, "labelled": False},
    ]

    assert labelled_frames(index(tmp_path, frames)) == [101]
