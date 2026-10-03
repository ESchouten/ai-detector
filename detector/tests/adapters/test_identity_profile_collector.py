from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import cv2
import numpy as np

from aidetector.adapters.identity_profile_collector import IdentityProfileCollector
from aidetector.adapters.identity_profiles import IdentityProfileStore
from aidetector.adapters.inference.continuous_identity import TrackEvidence
from aidetector.domain.live_identity import LiveTarget
from aidetector.domain.models import BoundingBox, CaptureStamp

AT = datetime(2026, 1, 1, tzinfo=UTC)
SOURCE = "rtsp://synthetic-user:synthetic-password@example.invalid/test"


def evidence(
    second, *, index=None, instance=0, generation=None, epoch="e1", image=None
):
    pixels = np.full((80, 128, 3), second % 256, np.uint8) if image is None else image
    pixels.flags.writeable = False
    return TrackEvidence(
        SOURCE,
        CaptureStamp(epoch, second * 30, float(second)),
        LiveTarget(
            str(instance), instance + 1 if generation is None else generation, 0
        ),
        BoundingBox(4, 4, 120, 75, "cow", 0.9, instance),
        0.9,
        pixels,
        second if index is None else index,
        AT + timedelta(seconds=second),
    )


def test_paced_eight_instances_share_images_and_collect_only_every_ten_seconds(
    tmp_path,
):
    now = [0.0]
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    try:
        for second in range(60):
            now[0] = second + 0.1
            pixels = np.full((80, 128, 3), second, np.uint8)
            for instance in range(8):
                sample = evidence(second, instance=instance, image=pixels)
                collector(sample)
                collector(sample)  # replay cannot count as another observation
        facts = store.snapshot()
        assert len(facts) == 48
        assert {f["analysis_index"] for f in facts} == {2, 12, 22, 32, 42, 52}
        assert len({f["episode_id"] for f in facts}) == 8
        assert store.usage()["images"] == 6
        assert store.usage()["profiles"] == 8
        assert all("identity_id" not in fact and "name" not in fact for fact in facts)
        assert all(f["image_resolution"] == "analysis" for f in facts)
        assert all(f["analysis_shape"] == f["image_shape"] for f in facts)
        assert "synthetic-password" not in str(facts)
    finally:
        collector.close()
        store.close()


def test_native_evidence_maps_inclusive_bounds_and_preserves_exact_capture(tmp_path):
    now = [0.0]
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    native = np.full((203, 307, 3), 123, np.uint8)
    native.flags.writeable = False
    try:
        for second in range(3):
            now[0] = second + 0.1
            collector(replace(evidence(second), native_image=native))
        fact = store.snapshot()[0]
        assert fact["image_resolution"] == "source"
        assert fact["image_encoding"] == "source-resolution-jpeg-quality95"
        assert fact["analysis_shape"] == [80, 128, 3]
        assert fact["image_shape"] == [203, 307, 3]
        assert fact["box"] == [9, 10, 290, 192]
        assert (fact["epoch"], fact["capture_sequence"], fact["analysis_index"]) == (
            "e1",
            60,
            2,
        )
        encoded = store.image(fact["id"])
        decoded = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape == native.shape and np.all(decoded == 123)
        # Full inclusive analysis bounds reach the final native pixel.
        for second in range(10, 13):
            now[0] = second + 0.1
            collector(
                replace(
                    evidence(second),
                    native_image=native,
                    box=BoundingBox(0, 0, 127, 79, "cow", track_id=0),
                )
            )
        assert store.snapshot()[-1]["box"] == [0, 0, 306, 202]
    finally:
        collector.close()
        store.close()


def test_analysis_gaps_split_episodes_without_resetting_per_instance_save_cadence(
    tmp_path,
):
    now = [0.0]
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    try:
        for second in [0, 1, 2, *range(4, 14)]:
            now[0] = second + 0.1
            collector(evidence(second))
        facts = sorted(store.snapshot(), key=lambda row: row["analysis_index"])
        assert [row["analysis_index"] for row in facts] == [2, 12]
        assert facts[0]["episode_id"] != facts[1]["episode_id"]
        assert facts[0]["profile_id"] == facts[1]["profile_id"]
    finally:
        collector.close()
        store.close()


def test_source_reset_new_generation_stale_frames_and_closed_collector(tmp_path):
    now = [0.0]
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    try:
        for second in range(3):
            now[0] = second + 0.1
            collector(evidence(second))
        # A tracker reset in the same capture epoch starts new analysis indices
        # and a new target generation. Old-generation callbacks cannot join it.
        for second in range(3, 6):
            now[0] = second + 0.1
            collector(evidence(second, index=second - 3, generation=9))
            collector(evidence(second, index=second - 3, generation=1))
        collector.source_changed(None)
        now[0] = 6.1
        collector(evidence(6, generation=9))
        collector.source_changed("e2")
        for second in range(7, 10):
            now[0] = second + 0.1
            collector(evidence(second, epoch="e1", generation=9))
            collector(evidence(second, epoch="e2", index=second - 7, generation=10))
        facts = store.snapshot()
        assert len(facts) == 3 and len({f["profile_id"] for f in facts}) == 3
        assert {(f["epoch"], f["generation"]) for f in facts} == {
            ("e1", 1),
            ("e1", 9),
            ("e2", 10),
        }
        collector.close()
        now[0] = 12.1
        collector(evidence(12, epoch="e2", generation=10))
        assert len(store.snapshot()) == 3
    finally:
        collector.close()
        store.close()


def test_disconnect_during_encoding_is_nonblocking_and_cannot_publish_old_evidence(
    tmp_path, monkeypatch
):
    from aidetector.adapters import identity_profiles

    entered, release = Event(), Event()
    original = identity_profiles.encode_jpeg

    def encode(image, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(image, **kwargs)

    monkeypatch.setattr(identity_profiles, "encode_jpeg", encode)
    now = [0.0]
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    try:
        for second in range(2):
            now[0] = second + 0.1
            collector(evidence(second))
        now[0] = 2.1
        with ThreadPoolExecutor(max_workers=1) as pool:
            native = np.full((161, 259, 3), 37, np.uint8)
            native.flags.writeable = False
            pending = pool.submit(collector, replace(evidence(2), native_image=native))
            try:
                assert entered.wait(timeout=5)
                collector.source_changed(None)
                collector.source_changed("e2")
            finally:
                release.set()
            pending.result(timeout=5)
        assert store.snapshot() == ()
        for second in range(3, 6):
            now[0] = second + 0.1
            collector(evidence(second, epoch="e2", index=second - 3, generation=9))
        assert len(store.snapshot()) == 1
        assert store.snapshot()[0]["epoch"] == "e2"
    finally:
        release.set()
        collector.close()
        store.close()


def test_expiry_during_encode_and_idle_selection_do_not_reuse_old_evidence(
    tmp_path, monkeypatch
):
    from aidetector.adapters import identity_profiles

    now = [0.0]
    original = identity_profiles.encode_jpeg

    def encode(image, **kwargs):
        now[0] += 1.0
        return original(image, **kwargs)

    monkeypatch.setattr(identity_profiles, "encode_jpeg", encode)
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    try:
        for second in range(3):
            now[0] = second + 0.1
            collector(evidence(second))
        assert store.snapshot() == ()
        monkeypatch.setattr(identity_profiles, "encode_jpeg", original)
        for second in range(3, 6):
            now[0] = second + 0.1
            collector(evidence(second))
        assert len(store.snapshot()) == 1
        now[0] = 20.0
        collector.maintain()
        assert len(store.snapshot()) == 1
        # An idle gap cannot immediately save using three old observations.
        collector(evidence(20, index=6))
        assert len(store.snapshot()) == 1
    finally:
        collector.close()
        store.close()


def test_expected_storage_failure_is_observable_and_retries_after_backoff(
    tmp_path, monkeypatch
):
    from aidetector.adapters import identity_profiles
    from aidetector.adapters.media import MediaError

    original = identity_profiles.encode_jpeg
    attempts = []

    def fail_once(image, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise MediaError("synthetic encoder failure")
        return original(image, **kwargs)

    monkeypatch.setattr(identity_profiles, "encode_jpeg", fail_once)
    now, statuses = [0.0], []
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(
        tmp_path, "run", SOURCE, clock=lambda: now[0], report_status=statuses.append
    )
    collector.source_changed("e1")
    try:
        for second in range(65):
            now[0] = second + 0.1
            collector(evidence(second))
        assert len(attempts) == 2
        assert len(statuses) == 1 and statuses[0].kind == "notice"
        assert store.snapshot()[0]["analysis_index"] == 62
    finally:
        collector.close()
        store.close()


def test_camera_mismatch_and_bounded_many_generations_do_not_share_episodes(tmp_path):
    import pytest

    now = [0.0]
    store = IdentityProfileStore(tmp_path, "observer")
    collector = IdentityProfileCollector(tmp_path, "run", SOURCE, clock=lambda: now[0])
    collector.source_changed("e1")
    try:
        with pytest.raises(ValueError, match="different camera"):
            collector(replace(evidence(0), source="another camera"))
        for generation in range(1, 601):
            for step in range(3):
                second = generation * 3 + step
                now[0] = second + 0.1
                collector(
                    evidence(
                        second, index=step, instance=generation, generation=generation
                    )
                )
        facts = store.snapshot()
        assert len(facts) == 500
        assert {r["generation"] for r in facts} == set(range(101, 601))
        assert len({r["episode_id"] for r in facts}) == 500
    finally:
        collector.close()
        store.close()


def test_initial_corrupt_store_is_optional_and_recovers_after_backoff(
    tmp_path, monkeypatch
):
    import sqlite3

    import pytest

    opened = []
    connect = sqlite3.connect

    def recording_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    database = tmp_path / "automatic" / "profiles.sqlite"
    database.parent.mkdir()
    database.write_bytes(b"not a SQLite database")
    now, statuses = [0.0], []
    collector = IdentityProfileCollector(
        tmp_path, "run", SOURCE, clock=lambda: now[0], report_status=statuses.append
    )
    collector.source_changed("e1")
    try:
        for second in range(3):
            now[0] = second + 0.1
            collector(evidence(second))
        assert len(statuses) == 1 and len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1")
        # Failed initialization released its connection. A repaired path is
        # retried only when the original sixty-second backoff expires.
        database.unlink()
        for second in range(3, 62):
            now[0] = second + 0.1
            collector(evidence(second))
            collector.maintain()
        assert not database.exists() and len(statuses) == 1
        now[0] = 62.1
        collector(evidence(62))
    finally:
        collector.close()
    observer = IdentityProfileStore(tmp_path, "observer")
    try:
        assert [row["analysis_index"] for row in observer.snapshot()] == [62]
    finally:
        observer.close()
    now[0] = 72.1
    collector.maintain()
    collector(evidence(72))  # close cannot lazily reopen or publish evidence


def test_unwritable_storage_parent_does_not_stop_collection_or_idle_worker(tmp_path):
    directory = tmp_path / "blocked-parent"
    directory.write_text("ordinary file prevents creating automatic directory")
    now, statuses = [0.0], []
    collector = IdentityProfileCollector(
        directory, "run", SOURCE, clock=lambda: now[0], report_status=statuses.append
    )
    collector.source_changed("e1")
    try:
        collector.maintain()
        for second in range(60):
            now[0] = second + 0.1
            collector(evidence(second))
            collector.maintain()
        assert len(statuses) == 1
        directory.unlink()
        now[0] = 60.1
        collector(evidence(60))
        assert (directory / "automatic" / "profiles.sqlite").exists()
    finally:
        collector.close()
    observer = IdentityProfileStore(directory, "observer")
    try:
        assert len(observer.snapshot()) == 1
    finally:
        observer.close()
