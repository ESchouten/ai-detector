import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from aidetector.adapters.operational_status import STATUS_PREFIX, JsonStatusReporter
from aidetector.application.status import StatusEvent


def test_protocol_is_versioned_hides_credentials_and_throttles_frame_traffic():
    output = StringIO()
    report = JsonStatusReporter(output)
    source = "rtsp://farmer:password@camera.example.test/live?token=secret"
    for _ in range(30):
        report(StatusEvent("frame", source))
    report(StatusEvent("recording", source))
    records = [
        json.loads(line.removeprefix(STATUS_PREFIX))
        for line in output.getvalue().splitlines()
    ]
    assert [record["event"] for record in records] == ["frame", "recording"]
    assert all(record["version"] == 1 for record in records)
    assert all(
        record["sourceKey"] == hashlib.sha256(source.encode()).hexdigest()
        for record in records
    )
    assert "password" not in output.getvalue()
    assert "secret" not in output.getvalue()


def test_concurrent_workers_emit_intact_independent_camera_records():
    output = StringIO()
    report = JsonStatusReporter(output)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(
            workers.map(
                lambda source: report(StatusEvent("frame", str(source))), range(100)
            )
        )
    records = [
        json.loads(line.removeprefix(STATUS_PREFIX))
        for line in output.getvalue().splitlines()
    ]
    assert len(records) == 100
    assert len({record["sourceKey"] for record in records}) == 100


def test_shared_camera_does_not_throttle_one_rules_inference_behind_another():
    output = StringIO()
    report = JsonStatusReporter(output)
    report(StatusEvent("inference", "camera", rule_id="detector-1"))
    report(StatusEvent("inference", "camera", rule_id="detector-2"))
    report(
        StatusEvent(
            "recording_failed", "camera", rule_id="detector-1", destination_id="disk-2"
        )
    )
    records = [
        json.loads(line.removeprefix(STATUS_PREFIX))
        for line in output.getvalue().splitlines()
    ]
    assert [record["ruleId"] for record in records] == [
        "detector-1",
        "detector-2",
        "detector-1",
    ]
    assert records[-1]["destinationId"] == "disk-2"


def test_queue_wait_is_throttled_per_rule_without_delaying_resume():
    output = StringIO()
    report = JsonStatusReporter(output)
    for _ in range(30):
        report(StatusEvent("waiting_delivery", rule_id="detector-1"))
        report(StatusEvent("waiting_delivery", rule_id="detector-2"))
    report(StatusEvent("processing_resumed", rule_id="detector-1"))
    records = [
        json.loads(line.removeprefix(STATUS_PREFIX))
        for line in output.getvalue().splitlines()
    ]
    assert [(item["event"], item["ruleId"]) for item in records] == [
        ("waiting_delivery", "detector-1"),
        ("waiting_delivery", "detector-2"),
        ("processing_resumed", "detector-1"),
    ]


def test_quick_capture_epochs_and_disconnects_are_never_throttled():
    output = StringIO()
    report = JsonStatusReporter(output)
    for epoch in ("first", "second"):
        report(StatusEvent("source_epoch", "camera", source_epoch=epoch))
        report(StatusEvent("frame", "camera"))
        report(StatusEvent("offline", "camera", "Disconnected"))
    records = [
        json.loads(line.removeprefix(STATUS_PREFIX))
        for line in output.getvalue().splitlines()
    ]
    assert [record["event"] for record in records] == [
        "source_epoch",
        "frame",
        "offline",
        "source_epoch",
        "offline",
    ]
    assert [record["sourceEpoch"] for record in records if "sourceEpoch" in record] == [
        "first",
        "second",
    ]


def test_late_old_epoch_result_cannot_throttle_the_first_result_after_reconnect(
    monkeypatch,
):
    monkeypatch.setattr("aidetector.adapters.operational_status.monotonic", lambda: 10)
    output = StringIO()
    report = JsonStatusReporter(output)
    for kind in ("inference", "processed"):
        # Every transition occurs within one rate-limit interval, including a
        # slow old batch that finishes after capture has already reconnected.
        report(StatusEvent("source_epoch", "camera", source_epoch="new"))
        for epoch in ("old", "old", "new", "new", "newer", "newer"):
            report(
                StatusEvent(kind, "camera", rule_id="detector-1", source_epoch=epoch)
            )
    records = [
        json.loads(line.removeprefix(STATUS_PREFIX))
        for line in output.getvalue().splitlines()
    ]
    for kind in ("inference", "processed"):
        assert [
            record["sourceEpoch"] for record in records if record["event"] == kind
        ] == ["old", "new", "newer"]
