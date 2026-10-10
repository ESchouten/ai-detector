import hashlib
import json
from datetime import datetime
from threading import Event
from time import monotonic, time

import numpy as np

from aidetector.adapters.live_preview import LivePreview, _atomic_json
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


def observation(track_id=17):
    return Observation(
        datetime(2026, 1, 1),
        np.zeros((16, 24, 3), dtype=np.uint8),
        {"cow": 0.9},
        (BoundingBox(1, 2, 10, 12, "cow", 0.9, track_id),),
    )


def test_nothing_is_published_without_a_valid_viewer_and_late_viewer_works(tmp_path):
    publisher = LivePreview(tmp_path)
    publish = publisher.observer("detector-1", ("camera",))
    key = lease(tmp_path, "camera", ["malformed lease"])
    file = tmp_path / "frames" / f"{key}.detector-1.json"
    with publisher.open():
        wait_for(lambda: read_record(tmp_path / "session.json"))
        publish("camera", observation())
        Event().wait(0.3)
        assert not file.exists()
        lease(tmp_path, "camera")

        def publish_until_visible():
            publish("camera", observation())
            return read_record(file)

        record = wait_for(publish_until_visible)
        assert record["sourceKey"] == key
    assert not (tmp_path / "session.json").exists()


def test_multiple_rules_publish_picture_size_and_boxes_and_overwrite(tmp_path):
    key = lease(tmp_path, "rtsp://user:secret@camera/live")
    publisher = LivePreview(tmp_path, interval=0.01)
    first = publisher.observer("detector-1", ("rtsp://user:secret@camera/live",))
    second = publisher.observer("detector-2", ("rtsp://user:secret@camera/live",))
    file = tmp_path / "frames" / f"{key}.detector-1.json"
    with publisher.open():
        wait_for(lambda: read_record(tmp_path / "session.json"))
        first("rtsp://user:secret@camera/live", observation(20))
        second("rtsp://user:secret@camera/live", observation(80))
        wait_for(lambda: len(list((tmp_path / "frames").glob("*.json"))) == 2)
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
                "trackId": 20,
            }
        ]
        assert record["image"] == {"width": 24, "height": 16}
        assert "secret" not in json.dumps(record)
        first("rtsp://user:secret@camera/live", observation(120))
        updated = wait_for(
            lambda: (
                (result := read_record(file))
                and result["publishedAt"] != record["publishedAt"]
                and result
            )
        )
        assert updated["boxes"][0]["trackId"] == 120
        assert len(list((tmp_path / "frames").iterdir())) == 2


def test_slow_write_does_not_block_inference_and_keeps_only_latest_pending(
    tmp_path, monkeypatch
):
    key = lease(tmp_path, "camera")
    entered, release = Event(), Event()
    values = []

    def write(path, record):
        if "ruleId" in record:
            values.append(record["boxes"][0]["trackId"])
            if len(values) == 1:
                entered.set()
                assert release.wait(5)
        _atomic_json(path, record)

    monkeypatch.setattr("aidetector.adapters.live_preview._atomic_json", write)
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


def test_write_failure_does_not_starve_other_rules_and_disconnect_stops_publication(
    tmp_path, monkeypatch, caplog
):
    key = lease(tmp_path, "camera")

    def write(path, record):
        if record.get("ruleId") == "detector-1":
            raise OSError("Preview folder is full")
        _atomic_json(path, record)

    monkeypatch.setattr("aidetector.adapters.live_preview._atomic_json", write)
    publisher = LivePreview(tmp_path, interval=0.01)
    first = publisher.observer("detector-1", ("camera",))
    second = publisher.observer("detector-2", ("camera",))
    file = tmp_path / "frames" / f"{key}.detector-2.json"
    with publisher.open():
        wait_for(lambda: read_record(tmp_path / "session.json"))
        first("camera", observation(1))
        second("camera", observation(2))
        record = wait_for(lambda: read_record(file))
        assert "Preview folder is full" in caplog.text
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
