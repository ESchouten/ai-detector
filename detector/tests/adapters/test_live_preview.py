import base64
import hashlib
import json
from datetime import datetime
from threading import Event
from time import monotonic, time

import cv2
import numpy as np

from aidetector.adapters.live_preview import LivePreview
from aidetector.adapters.media import MediaError
from aidetector.adapters.media.images import encode_jpeg
from aidetector.domain.models import BoundingBox, Observation


def wait_for(condition):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = condition()
        if result:
            return result
        Event().wait(0.02)
    raise AssertionError("Live preview did not progress")


def read_record(file):
    try:
        return json.loads(file.read_text())
    except FileNotFoundError:
        return None


def lease(directory, source, value=None):
    source_key = hashlib.sha256(source.encode()).hexdigest()
    leases = directory / "leases"
    leases.mkdir(parents=True, exist_ok=True)
    (leases / f"{source_key}.json").write_text(
        json.dumps(
            value if value is not None else {"version": 1, "expiresAt": time() + 12}
        )
    )
    return source_key


def observation(value=0):
    return Observation(
        datetime(2026, 1, 1),
        np.full((16, 24, 3), value, dtype=np.uint8),
        {"cow": 0.9},
        (BoundingBox(1, 2, 10, 12, "cow", 0.9, 17),),
    )


def test_no_encoding_without_a_valid_viewer_and_late_viewer_works(
    tmp_path, monkeypatch
):
    encoded = []

    def encode(image, quality):
        encoded.append(image)
        return encode_jpeg(image, quality)

    monkeypatch.setattr("aidetector.adapters.live_preview.encode_jpeg", encode)
    publisher = LivePreview(tmp_path)
    publish = publisher.observer("detector-1", ("camera",))
    key = lease(tmp_path, "camera", ["malformed lease"])
    file = tmp_path / "frames" / f"{key}.detector-1.json"
    with publisher.open():
        wait_for(lambda: read_record(tmp_path / "session.json"))
        publish("camera", observation())
        Event().wait(0.3)
        assert encoded == []
        lease(tmp_path, "camera")

        def publish_until_visible():
            publish("camera", observation())
            return read_record(file)

        record = wait_for(publish_until_visible)
        assert record["sourceKey"] == key
    assert not (tmp_path / "session.json").exists()


def test_multiple_rules_publish_matching_frame_and_boxes_and_overwrite(tmp_path):
    key = lease(tmp_path, "rtsp://user:secret@camera/live")
    publisher = LivePreview(tmp_path, interval=0.01)
    first = publisher.observer("detector-1", ("rtsp://user:secret@camera/live",))
    second = publisher.observer("detector-2", ("rtsp://user:secret@camera/live",))
    file = tmp_path / "frames" / f"{key}.detector-1.json"
    with publisher.open():

        def initial():
            first("rtsp://user:secret@camera/live", observation(20))
            second("rtsp://user:secret@camera/live", observation(80))
            return len(list((tmp_path / "frames").glob("*.json"))) == 2

        wait_for(initial)
        record = read_record(file)
        assert record["runId"] == publisher.run_id
        assert record["boxes"] == [
            {
                "x1": 1,
                "y1": 2,
                "x2": 10,
                "y2": 12,
                "label": "cow",
                "confidence": 0.9,
                "trackId": 17,
            }
        ]
        image = cv2.imdecode(
            np.frombuffer(base64.b64decode(record["image"]["jpeg"]), np.uint8),
            cv2.IMREAD_COLOR,
        )
        assert image.shape == (16, 24, 3)
        assert np.all(image == 20)
        assert "secret" not in json.dumps(record)
        first("rtsp://user:secret@camera/live", observation(120))
        updated = wait_for(
            lambda: (
                (result := read_record(file))
                and result["publishedAt"] != record["publishedAt"]
                and result
            )
        )
        assert updated["image"]["jpeg"] != record["image"]["jpeg"]
        assert len(list((tmp_path / "frames").iterdir())) == 2


def test_slow_encoder_does_not_block_inference_and_keeps_only_latest_pending(
    tmp_path, monkeypatch
):
    key = lease(tmp_path, "camera")
    entered, release = Event(), Event()
    values = []

    def encode(image, quality):
        values.append(int(image[0, 0, 0]))
        if len(values) == 1:
            entered.set()
            assert release.wait(5)
        return encode_jpeg(image, quality)

    monkeypatch.setattr("aidetector.adapters.live_preview.encode_jpeg", encode)
    publisher = LivePreview(tmp_path, interval=0.01)
    publish = publisher.observer("detector-1", ("camera",))
    with publisher.open():
        try:
            wait_for(lambda: (publish("camera", observation(1)), entered.is_set())[1])
            for value in range(2, 100):
                publish("camera", observation(value))
            assert values == [1]
        finally:
            release.set()
        wait_for(lambda: len(values) == 2)
        assert values == [1, 99]
        assert read_record(tmp_path / "frames" / f"{key}.detector-1.json")


def test_encoder_failure_does_not_starve_other_rules_and_disconnect_stops_publication(
    tmp_path, monkeypatch, caplog
):
    key = lease(tmp_path, "camera")

    def encode(image, quality):
        if image[0, 0, 0] == 1:
            raise MediaError("Invalid preview image")
        return encode_jpeg(image, quality)

    monkeypatch.setattr("aidetector.adapters.live_preview.encode_jpeg", encode)
    publisher = LivePreview(tmp_path, interval=0.01)
    first = publisher.observer("detector-1", ("camera",))
    second = publisher.observer("detector-2", ("camera",))
    file = tmp_path / "frames" / f"{key}.detector-2.json"
    with publisher.open():

        def publish():
            first("camera", observation(1))
            second("camera", observation(2))
            return read_record(file)

        record = wait_for(publish)
        assert "Invalid preview image" in caplog.text
        (tmp_path / "leases" / f"{key}.json").unlink()
        second("camera", observation(3))
        Event().wait(0.5)
        assert read_record(file) == record


def test_new_run_removes_old_frames_and_owned_temporary_files(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    key = "a" * 64
    (frames / f"{key}.detector-1.json").write_text("old run")
    (frames / f"{key}.detector-1.{'b' * 32}.tmp").write_text("unfinished")
    (frames / "unrelated.txt").write_text("keep")
    with LivePreview(tmp_path).open():
        wait_for(lambda: read_record(tmp_path / "session.json"))
        assert [file.name for file in frames.iterdir()] == ["unrelated.txt"]
