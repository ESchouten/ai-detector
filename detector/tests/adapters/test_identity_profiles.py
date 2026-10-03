import hashlib
from datetime import UTC, datetime, timedelta

import cv2
import numpy as np

from aidetector.adapters.identity_profiles import IdentityProfileStore
from aidetector.domain.live_identity import LiveTarget
from aidetector.domain.models import BoundingBox, CaptureStamp

AT = datetime(2026, 1, 1, tzinfo=UTC)
BOX = BoundingBox(2, 2, 25, 25, "cow", 1.0, 1)
SOURCE = "rtsp://synthetic-user:synthetic-password@example.invalid/camera"


def save(
    store,
    sequence,
    *,
    instance="instance",
    epoch="epoch",
    generation=1,
    image=None,
    episode="episode",
):
    return store.save(
        SOURCE,
        CaptureStamp(epoch, sequence, float(sequence)),
        LiveTarget(instance, generation, 0),
        AT + timedelta(seconds=sequence),
        BOX,
        0.9,
        np.full((32, 32, 3), sequence % 256, np.uint8) if image is None else image,
        episode_id=episode,
        analysis_index=sequence,
    )


def test_full_analyzed_frame_shared_without_credentials_or_identity_assignment(
    tmp_path, monkeypatch
):
    from aidetector.adapters import identity_profiles

    class CountedImage(np.ndarray):
        reads = 0

        def tobytes(self, order="C"):
            type(self).reads += 1
            return super().tobytes(order)

    calls = []
    original = identity_profiles.encode_jpeg

    def encode(image, **kwargs):
        calls.append(image.shape)
        return original(image, **kwargs)

    monkeypatch.setattr(identity_profiles, "encode_jpeg", encode)
    store = IdentityProfileStore(tmp_path, "run", clock=lambda: AT)
    try:
        image = (
            np.random.default_rng(42)
            .integers(0, 256, (32, 32, 3), np.uint8)
            .view(CountedImage)
        )
        first = save(store, 1, image=image)
        second = save(store, 1, instance="another", image=image)
        assert first and second and first != second
        assert len(calls) == 1
        assert CountedImage.reads == 1
        assert store.usage()["images"] == 1
        data = store.snapshot()
        assert len(data) == 2
        assert all(
            row["status"] == "anonymous_observation_not_biological_identity"
            for row in data
        )
        assert "synthetic-password" not in str(data) and "synthetic-user" not in str(
            data
        )
        encoded = store.image(first)
        assert encoded is not None
        assert encoded == store.image(second)
        assert hashlib.sha256(encoded).hexdigest() == data[0]["encoded_sha256"]
        assert data[0]["original_pixels_sha256"] != data[0]["encoded_sha256"]
        assert (
            cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR).shape
            == image.shape
        )
        assert data[0]["episode_id"] == "episode"
        assert "identity" not in data[0] and "name" not in data[0]
    finally:
        store.close()


def test_oversized_analyzed_frame_skips_before_hashing_or_encoding(
    tmp_path, monkeypatch
):
    from aidetector.adapters import identity_profiles

    calls = []
    monkeypatch.setattr(
        identity_profiles, "encode_jpeg", lambda *_args, **_kwargs: calls.append(1)
    )
    store = IdentityProfileStore(tmp_path, "run", clock=lambda: AT)
    try:
        # A broadcast view exercises the logical frame bound without allocating
        # or copying a huge image just for this boundary test.
        image = np.broadcast_to(np.zeros((1, 1, 3), np.uint8), (4096, 4096, 3))
        assert save(store, 1, image=image) is None
        assert calls == [] and store.snapshot() == ()
    finally:
        store.close()


def test_scoped_generations_epochs_and_runs_never_merge(tmp_path):
    for run in ("first", "second"):
        store = IdentityProfileStore(tmp_path, run, clock=lambda: AT)
        try:
            for epoch, generation in (("e1", 1), ("e1", 2), ("e2", 1)):
                assert save(store, 1, epoch=epoch, generation=generation)
        finally:
            store.close()
    store = IdentityProfileStore(tmp_path, "third", clock=lambda: AT)
    try:
        rows = store.snapshot()
        assert len(rows) == 6 and len({r["profile_id"] for r in rows}) == 6
    finally:
        store.close()


def test_idempotent_and_stale_observations_do_not_modify_original_facts(tmp_path):
    store = IdentityProfileStore(tmp_path, "run", clock=lambda: AT)
    try:
        first = save(store, 10)
        assert save(store, 10) == first
        assert save(store, 9) is None
        assert save(store, 10, episode="new-episode") is None
        assert save(store, 10, image=np.zeros((32, 32, 3), np.uint8)) is None
        assert len(store.snapshot()) == 1
    finally:
        store.close()


def test_automatic_retention_continues_after_200_samples_and_keeps_manual_files(
    tmp_path,
):
    manual = tmp_path / "catalog.json"
    manual.write_text("manual sentinel")
    photo = tmp_path / "images" / "confirmed.jpg"
    photo.parent.mkdir()
    photo.write_bytes(b"confirmed sentinel")
    now = [AT]
    store = IdentityProfileStore(
        tmp_path, "run", max_candidates=2, clock=lambda: now[0]
    )
    try:
        for i in range(205):
            now[0] = AT + timedelta(seconds=i)
            assert save(store, i)
        assert sorted(r["capture_sequence"] for r in store.snapshot()) == [203, 204]
        assert store.usage()["images"] == 2
        assert (
            manual.read_text() == "manual sentinel"
            and photo.read_bytes() == b"confirmed sentinel"
        )
    finally:
        store.close()


def test_shared_images_survive_one_profile_eviction_and_expire_with_last_reference(
    tmp_path,
):
    now = [AT]
    image = np.zeros((32, 32, 3), np.uint8)
    store = IdentityProfileStore(
        tmp_path,
        "run",
        max_profiles=2,
        max_age=timedelta(seconds=5),
        clock=lambda: now[0],
    )
    try:
        first = save(store, 1, instance="a", image=image)
        now[0] += timedelta(seconds=1)
        second = save(store, 1, instance="b", image=image)
        now[0] += timedelta(seconds=1)
        third = save(store, 1, instance="c", image=image)
        assert store.image(first) is None and store.image(second) == store.image(third)
        assert store.usage()["profiles"] == 2 and store.usage()["images"] == 1
        now[0] += timedelta(seconds=6)
        store.maintain()
        assert store.snapshot() == () and store.usage()["images"] == 0
    finally:
        store.close()


def test_actual_database_bytes_remain_bounded_while_old_candidates_evicted(tmp_path):
    budget = 256 * 1024
    now = [AT]
    rng = np.random.default_rng(9)
    store = IdentityProfileStore(
        tmp_path, "run", max_bytes=budget, clock=lambda: now[0]
    )
    try:
        ids = []
        for i in range(20):
            now[0] = AT + timedelta(seconds=i)
            sample = save(store, i, image=rng.integers(0, 256, (192, 192, 3), np.uint8))
            assert sample is not None
            ids.append(sample)
            assert store.usage()["database_bytes"] <= budget
        assert store.image(ids[0]) is None and store.image(ids[-1]) is not None
        previous = store.snapshot()
        assert (
            save(store, 21, image=rng.integers(0, 256, (900, 900, 3), np.uint8)) is None
        )
        assert store.snapshot() == previous
    finally:
        store.close()


def test_reopening_enforces_lower_candidate_profile_and_disk_limits_without_new_save(
    tmp_path,
):
    now = [AT]
    rng = np.random.default_rng(8)
    store = IdentityProfileStore(
        tmp_path, "run", max_bytes=2 * 1024**2, clock=lambda: now[0]
    )
    try:
        for instance in range(6):
            for sequence in range(3):
                now[0] += timedelta(seconds=1)
                assert save(
                    store,
                    sequence,
                    instance=str(instance),
                    image=rng.integers(0, 256, (128, 128, 3), np.uint8),
                )
        assert store.usage()["database_bytes"] > 128 * 1024
    finally:
        store.close()
    # Size is reduced immediately on opening, before any new candidate writes.
    store = IdentityProfileStore(
        tmp_path, "next", max_bytes=128 * 1024, clock=lambda: now[0]
    )
    try:
        assert store.usage()["database_bytes"] <= 128 * 1024
        assert 0 < len(store.snapshot()) < 18
    finally:
        store.close()
    store = IdentityProfileStore(
        tmp_path,
        "third",
        max_candidates=1,
        max_profiles=1,
        max_bytes=128 * 1024,
        clock=lambda: now[0],
    )
    try:
        assert store.usage()["profiles"] == 1
        assert store.usage()["candidates"] == 1
        assert store.usage()["images"] == 1
    finally:
        store.close()
