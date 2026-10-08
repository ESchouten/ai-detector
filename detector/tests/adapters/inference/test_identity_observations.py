import json
import sqlite3
from concurrent.futures import CancelledError, Executor, Future
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from threading import Event

import numpy as np
import pytest

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.identity import (
    DeferredEncoder,
    EmbeddingCache,
    download_identity_asset,
)
from aidetector.adapters.inference.identity_gallery import prepare_gallery
from aidetector.adapters.inference.identity_observations import (
    GalleryIdentifier,
    distinct_identity_scores,
    usable_crop,
)
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import (
    BoundingBox,
    CaptureStamp,
    IdentityMatch,
    Observation,
)

START = datetime(2026, 1, 1)
BELLA, DAISY = "a" * 32, "b" * 32
BLUE, GREEN = (240, 0, 0), (0, 240, 0)


class ImmediateExecutor(Executor):
    """Resolve background I/O deterministically for matching-policy tests."""

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)
        return future


class ManualExecutor(Executor):
    def __init__(self):
        self.pending = []

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def finish_next(self):
        future, fn, args, kwargs = self.pending.pop(0)
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)


class FakeEncoder:
    dimension = 384

    def __init__(self, fingerprint="model-v1:size224"):
        self.fingerprint = fingerprint
        self.calls = []
        self.failure = False

    def encode(self, images):
        self.calls.append([image.copy() for image in images])
        if self.failure:
            raise RuntimeError("Encoder unavailable")
        vectors = np.zeros((len(images), 384), dtype=np.float32)
        for row, image in enumerate(images):
            channel = int(image.mean(axis=(0, 1)).argmax())
            vectors[row, channel] = 1
        return vectors


def write_gallery(directory, revision, identities):
    catalog = Catalog.model_validate({"revision": revision, "identities": identities})
    pending = directory / "catalog.tmp"
    pending.write_text(catalog.model_dump_json(), encoding="utf-8")
    pending.replace(directory / "catalog.json")


@pytest.fixture
def environment(tmp_path):
    catalog = IdentityCatalog(tmp_path / "identities")
    samples = [
        catalog.save_sighting(
            np.full((40, 40, 3), color, dtype=np.uint8),
            "enrollment",
            START,
            index,
            IdentityMatch(),
        )
        for index, color in enumerate((BLUE, GREEN))
    ]
    identities = [
        {"id": BELLA, "name": "Bella", "samples": [samples[0]]},
        {"id": DAISY, "name": "Daisy", "samples": [samples[1]]},
    ]
    write_gallery(catalog.directory, 1, identities)
    cache = EmbeddingCache(tmp_path / "embeddings.sqlite")
    encoder = FakeEncoder()
    identifier = GalleryIdentifier(
        IdentityConfig(labels=("cow",), min_crop_size=32),
        catalog,
        partial(prepare_gallery, store=catalog, encoder=encoder, cache=cache),
        ImmediateExecutor(),
    )
    try:
        yield identifier, catalog, encoder, identities
    finally:
        cache.close()


def observation(second, *subjects, capture=None):
    image = np.zeros((200, 240, 3), dtype=np.uint8)
    boxes = []
    for track_id, color, coordinates, label in subjects:
        x1, y1, x2, y2 = coordinates
        image[max(0, y1) : min(200, y2), max(0, x1) : min(240, x2)] = color
        boxes.append(BoundingBox(x1, y1, x2, y2, label, 0.95, track_id))
    return Observation(
        START + timedelta(seconds=second),
        image,
        {"cow": 0.95},
        tuple(boxes),
        capture=capture,
    )


def cow(track=7, color=BLUE, coordinates=(10, 10, 50, 50)):
    return track, color, coordinates, "cow"


def test_identity_requires_three_sampled_frames_and_preserves_original_observation(
    environment,
):
    identifier, catalog, encoder, _ = environment
    original_catalog = (catalog.directory / "catalog.json").read_bytes()
    for second in (0, 0.2, 0.7, 1):
        result = identifier.identify("camera", observation(second, cow()))
        assert result.boxes[0].identity.identity_id is None
    original = observation(2, cow(), (8, GREEN, (70, 10, 110, 50), "horse"))

    recognized = identifier.identify("camera", original)

    assert recognized.date == original.date
    assert recognized.image is original.image
    assert recognized.confidence is original.confidence
    assert recognized.boxes[0].identity == IdentityMatch(BELLA, "Bella", 1.0)
    assert recognized.boxes[0].track_id == 7
    assert recognized.boxes[1] is original.boxes[1]
    assert original.boxes[0].identity is None
    assert (
        sum(len(batch) for batch in encoder.calls) == 5
    )  # Two gallery crops and three samples.
    assert (catalog.directory / "catalog.json").read_bytes() == original_catalog
    assert len(list((catalog.directory / "sightings").glob("*.json"))) == 3
    captured = [
        json.loads(path.read_text())
        for path in (catalog.directory / "sightings").glob("*.json")
    ]
    assert [item["gallery_revision"] for item in captured if item["track_id"] == 7] == [
        1
    ]


def test_quick_reconnect_restarts_only_that_cameras_identity_and_sampling(environment):
    identifier, _, encoder, _ = environment
    for second in range(3):
        old = identifier.identify(
            "camera",
            observation(second, cow(), capture=CaptureStamp("old", second, second)),
        )
        identifier.identify(
            "other",
            observation(
                second, cow(color=GREEN), capture=CaptureStamp("other", second, second)
            ),
        )
    assert old.boxes[0].identity.identity_id == BELLA
    calls = len(encoder.calls)
    returned = identifier.identify(
        "camera", observation(2.1, cow(), capture=CaptureStamp("new", 0, 2.1))
    )
    assert returned.boxes[0].identity.identity_id is None
    assert len(encoder.calls) == calls + 1  # No cached pre-reconnect sample.
    unaffected = identifier.identify(
        "other",
        observation(2.2, cow(color=GREEN), capture=CaptureStamp("other", 3, 2.2)),
    )
    assert unaffected.boxes[0].identity.identity_id == DAISY
    for sequence, second in enumerate((3.2, 4.3), start=1):
        returned = identifier.identify(
            "camera",
            observation(second, cow(), capture=CaptureStamp("new", sequence, second)),
        )
        assert (returned.boxes[0].identity.identity_id == BELLA) == (sequence == 2)


@pytest.mark.parametrize(
    "wall,monotonic_at",
    [(2.1, 20), (20, 3), (-10, 3)],
    ids=["capture-gap", "wall-gap", "wall-clock-reversal"],
)
def test_discontinuous_clock_requires_fresh_identity_agreement(
    environment, wall, monotonic_at
):
    identifier, _, _, _ = environment
    for second in range(3):
        identifier.identify(
            "camera",
            observation(second, cow(), capture=CaptureStamp("epoch", second, second)),
        )
    for offset in range(3):
        stamp = CaptureStamp("epoch", 3 + offset, monotonic_at + offset)
        result = identifier.identify(
            "camera", observation(wall + offset, cow(), capture=stamp)
        )
        assert result.capture is stamp
        assert (result.boxes[0].identity.identity_id == BELLA) == (offset == 2)


def test_duplicate_and_delayed_frames_neither_display_names_nor_add_evidence(
    environment,
):
    identifier, catalog, encoder, _ = environment
    for second in range(3):
        latest = identifier.identify(
            "camera",
            observation(second, cow(), capture=CaptureStamp("epoch", second, second)),
        )
    assert latest.boxes[0].identity.identity_id == BELLA
    calls = len(encoder.calls)
    files = set((catalog.directory / "sightings").iterdir())
    delayed = replace(latest, date=START + timedelta(seconds=20))
    for stale in (
        latest,
        delayed,
        observation(1, cow(), capture=CaptureStamp("epoch", 1, 1)),
    ):
        assert identifier.identify("camera", stale).boxes[0].identity is None
    assert len(encoder.calls) == calls
    assert set((catalog.directory / "sightings").iterdir()) == files
    fresh = identifier.identify(
        "camera", observation(3, cow(), capture=CaptureStamp("epoch", 3, 3))
    )
    assert fresh.boxes[0].identity.identity_id == BELLA


def test_metadata_free_repeated_timestamps_do_not_reuse_a_displayed_name(environment):
    identifier, _, encoder, _ = environment
    for second in range(3):
        latest = identifier.identify("camera", observation(second, cow()))
    calls = len(encoder.calls)
    assert identifier.identify("camera", latest).boxes[0].identity is None
    assert len(encoder.calls) == calls
    assert (
        identifier.identify("camera", observation(-1, cow())).boxes[0].identity is None
    )
    assert len(encoder.calls) == calls
    for second in range(3):
        result = identifier.identify("camera", observation(second, cow()))
        assert (result.boxes[0].identity.identity_id == BELLA) == (second == 2)


def test_reversed_capture_clock_discards_that_frame_and_clears_prior_names(environment):
    identifier, _, encoder, _ = environment
    for second in range(3):
        identifier.identify(
            "camera",
            observation(second, cow(), capture=CaptureStamp("epoch", second, second)),
        )
    calls = len(encoder.calls)
    reversed_clock = observation(3, cow(), capture=CaptureStamp("epoch", 3, 1))
    assert identifier.identify("camera", reversed_clock).boxes[0].identity is None
    assert len(encoder.calls) == calls
    for offset in range(3):
        result = identifier.identify(
            "camera",
            observation(
                4 + offset, cow(), capture=CaptureStamp("epoch", 4 + offset, 2 + offset)
            ),
        )
        assert (result.boxes[0].identity.identity_id == BELLA) == (offset == 2)


def test_geometry_change_clears_identity_even_without_capture_metadata(environment):
    identifier, _, _, _ = environment
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))
    for offset in range(3):
        original = observation(2.1 + offset, cow())
        changed = replace(
            original, image=np.pad(original.image, ((0, 10), (0, 0), (0, 0)))
        )
        result = identifier.identify("camera", changed)
        assert (result.boxes[0].identity.identity_id == BELLA) == (offset == 2)


def test_removed_gallery_reference_clears_previously_confirmed_identity(environment):
    identifier, catalog, _, identities = environment
    for second in range(3):
        result = identifier.identify("camera", observation(second, cow()))
    assert result.boxes[0].identity.identity_id == BELLA

    write_gallery(catalog.directory, 2, identities[1:])
    assert (
        identifier.identify("camera", observation(2.2, cow()))
        .boxes[0]
        .identity.identity_id
        is None
    )
    write_gallery(catalog.directory, 3, identities)
    for second in (3, 4):
        assert (
            identifier.identify("camera", observation(second, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    assert (
        identifier.identify("camera", observation(5, cow()))
        .boxes[0]
        .identity.identity_id
        == BELLA
    )


def test_corrected_reference_changes_identity_only_after_fresh_agreement(environment):
    identifier, catalog, _, identities = environment
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))
    corrected = [
        {**identities[0], "samples": identities[1]["samples"]},
        {**identities[1], "samples": identities[0]["samples"]},
    ]
    write_gallery(catalog.directory, 2, corrected)

    for second in (3, 4):
        assert (
            identifier.identify("camera", observation(second, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    assert identifier.identify("camera", observation(5, cow())).boxes[
        0
    ].identity == IdentityMatch(DAISY, "Daisy", 1)


def test_two_simultaneous_subjects_cannot_accumulate_the_same_identity(environment):
    identifier, _, _, _ = environment
    for second in range(4):
        result = identifier.identify(
            "camera", observation(second, cow(), cow(8, coordinates=(70, 10, 110, 50)))
        )
        assert all(box.identity.identity_id is None for box in result.boxes)
    for second in (4, 5):
        assert (
            identifier.identify("camera", observation(second, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    assert (
        identifier.identify("camera", observation(6, cow()))
        .boxes[0]
        .identity.identity_id
        == BELLA
    )


def test_staggered_sampling_detects_collisions_with_a_pending_track_candidate(
    environment,
):
    identifier, _, _, _ = environment
    identifier.identify("camera", observation(0, cow()))

    for second in (0.5, 1, 1.5, 2, 2.5, 3):
        result = identifier.identify(
            "camera",
            observation(second, cow(), cow(8, coordinates=(70, 10, 110, 50))),
        )
        assert all(box.identity.identity_id is None for box in result.boxes)


def test_unusable_crop_invalidates_cached_confirmation_before_next_sample(environment):
    identifier, _, _, _ = environment
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))

    obstructed = identifier.identify(
        "camera", observation(2.1, cow(), cow(8, GREEN, coordinates=(30, 10, 70, 50)))
    )
    assert all(box.identity.identity_id is None for box in obstructed.boxes)
    assert (
        identifier.identify("camera", observation(2.2, cow()))
        .boxes[0]
        .identity.identity_id
        is None
    )


def test_cached_collision_clears_every_tracks_confirmation(environment):
    identifier, _, _, _ = environment
    # Two independent views can recognize the same cow at different times. A
    # new second subject matching that cow must invalidate the cached first one.
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))
    collision = identifier.identify(
        "camera", observation(2.2, cow(), cow(8, coordinates=(70, 10, 110, 50)))
    )
    assert all(box.identity.identity_id is None for box in collision.boxes)
    assert (
        identifier.identify("camera", observation(2.3, cow()))
        .boxes[0]
        .identity.identity_id
        is None
    )


def test_briefly_missed_track_keeps_its_agreement(environment):
    identifier, _, _, _ = environment
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))

    assert identifier.identify("camera", observation(3)).boxes == ()
    assert (
        identifier.identify("camera", observation(4, cow()))
        .boxes[0]
        .identity.identity_id
        == BELLA
    )


def test_track_gone_for_longer_than_the_gap_needs_fresh_agreement(environment):
    identifier, _, _, _ = environment
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))

    for second in range(3, 9):
        assert identifier.identify("camera", observation(second)).boxes == ()
    for second in (9, 10):
        assert (
            identifier.identify("camera", observation(second, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    assert (
        identifier.identify("camera", observation(11, cow()))
        .boxes[0]
        .identity.identity_id
        == BELLA
    )


def test_live_encoder_failure_does_not_become_an_unknown_identity(environment):
    identifier, catalog, encoder, _ = environment
    identifier.identify("camera", observation(0, cow()))
    evidence_before = set((catalog.directory / "sightings").glob("*.json"))
    encoder.failure = True

    with pytest.raises(RuntimeError, match="Encoder unavailable"):
        identifier.identify("camera", observation(1, cow()))

    assert set((catalog.directory / "sightings").glob("*.json")) == evidence_before


def test_deleted_gallery_image_reports_unavailability_without_erasing_the_herd(
    environment, caplog
):
    identifier, catalog, _, identities = environment
    (catalog.directory / "images" / f"{identities[0]['samples'][0]}.jpg").unlink()
    statuses = []
    identifier.report_status = statuses.append
    original = observation(0, cow())
    assert identifier.identify("camera", original) is original
    assert "missing or unreadable" in caplog.text
    assert statuses[-1].kind == "identity_failed"
    assert len(catalog.load().identities) == 2


@pytest.mark.parametrize(
    "coordinates, other, expected",
    [
        ((10, 10, 42, 42), None, True),
        ((10, 10, 41, 42), None, False),
        ((0, 10, 40, 50), None, False),
        ((10, 10, 239, 50), None, False),
        ((10, 10, 50, 50), (30, 10, 70, 50), False),
        ((10, 10, 50, 50), (42, 10, 82, 50), True),
    ],
)
def test_crop_quality_rejects_tiny_clipped_and_obscured_subjects(
    coordinates, other, expected
):
    box = BoundingBox(*coordinates)
    boxes = (box,) if other is None else (box, BoundingBox(*other))
    assert usable_crop(box, boxes, 240, 200, 32, 0.2) is expected


def test_multiple_references_are_reduced_to_one_score_per_distinct_identity():
    gallery = np.asarray([[1, 0], [0, 1], [0.8, 0.6]], dtype=np.float32)
    scores = distinct_identity_scores(
        np.asarray([[1, 0], [0, 1]], dtype=np.float32),
        gallery,
        ((BELLA, "Bella"), (DAISY, "Daisy"), (BELLA, "Bella")),
    )
    assert scores[0] == [
        IdentityMatch(BELLA, "Bella", 1),
        IdentityMatch(DAISY, "Daisy", 0),
    ]
    assert scores[1] == [
        IdentityMatch(BELLA, "Bella", pytest.approx(0.6)),
        IdentityMatch(DAISY, "Daisy", 1),
    ]


def test_a_score_can_be_the_mean_of_an_identitys_nearest_references():
    gallery = np.asarray([[1, 0], [0.8, 0.6], [0, 1], [0.6, 0.8]], dtype=np.float32)
    scores = distinct_identity_scores(
        np.asarray([[1, 0]], dtype=np.float32),
        gallery,
        ((BELLA, "Bella"), (BELLA, "Bella"), (BELLA, "Bella"), (DAISY, "Daisy")),
        neighbours=2,
    )
    # Bella's two nearest of three; Daisy has one reference and keeps its score.
    assert scores[0] == [
        IdentityMatch(BELLA, "Bella", pytest.approx(0.9)),
        IdentityMatch(DAISY, "Daisy", pytest.approx(0.6)),
    ]


def test_descriptions_side_by_side_are_scored_apart_and_then_averaged():
    # The first description finds Bella's first photograph, the second her
    # second: each takes its own nearest, a mix of the two would find neither.
    gallery = np.asarray([[1, 0, 0, 1], [0, 1, 1, 0], [0, 1, 0, 1]], dtype=np.float32)
    scores = distinct_identity_scores(
        np.asarray([[1, 0, 1, 0]], dtype=np.float32),
        gallery,
        ((BELLA, "Bella"), (BELLA, "Bella"), (DAISY, "Daisy")),
        parts=(2, 2),
    )
    assert scores[0] == [
        IdentityMatch(BELLA, "Bella", 1),
        IdentityMatch(DAISY, "Daisy", 0),
    ]


def test_empty_gallery_returns_no_candidates_for_each_query():
    assert distinct_identity_scores(
        np.asarray([[1, 0], [0, 1]], dtype=np.float32),
        np.empty((0, 2), dtype=np.float32),
        (),
    ) == [[], []]


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_embedding_cannot_become_an_accepted_gallery_score(value):
    with pytest.raises(ValueError, match="finite"):
        distinct_identity_scores(
            np.asarray([[value, 1]], dtype=np.float32),
            np.asarray([[1, 0], [0, 1]], dtype=np.float32),
            ((BELLA, "Bella"), (DAISY, "Daisy")),
        )


def test_embedding_cache_reuses_pixels_and_separates_model_size_and_shape(tmp_path):
    encoder = FakeEncoder()
    image = np.full((40, 40, 3), BLUE, dtype=np.uint8)
    cache_path = tmp_path / "embeddings.sqlite"
    cache = EmbeddingCache(cache_path)
    try:
        first = cache.encode(encoder, [image, image.copy()])
        assert len(encoder.calls) == 1 and len(encoder.calls[0]) == 1
        np.testing.assert_array_equal(first[0], first[1])
        np.testing.assert_array_equal(cache.encode(encoder, [image]), first[:1])
        assert len(encoder.calls) == 1
        changed_pixel = image.copy()
        changed_pixel[0, 0, 0] -= 1
        cache.encode(encoder, [changed_pixel, image.reshape(20, 80, 3)])
        assert len(encoder.calls[1]) == 2
        model = FakeEncoder("model-v2:size224")
        size = FakeEncoder("model-v1:size336")
        cache.encode(model, [image])
        cache.encode(size, [image])
        assert len(model.calls) == len(size.calls) == 1
    finally:
        cache.close()
    reopened = EmbeddingCache(cache_path)
    try:
        before = len(encoder.calls)
        np.testing.assert_array_equal(reopened.encode(encoder, [image]), first[:1])
        assert len(encoder.calls) == before
    finally:
        reopened.close()


def test_failed_encoder_is_not_cached_as_a_successful_empty_result(tmp_path):
    encoder = FakeEncoder()
    encoder.failure = True
    image = np.full((40, 40, 3), BLUE, dtype=np.uint8)
    cache = EmbeddingCache(tmp_path / "embeddings.sqlite")
    try:
        with pytest.raises(RuntimeError, match="Encoder unavailable"):
            cache.encode(encoder, [image])
        encoder.failure = False
        assert cache.encode(encoder, [image]).shape == (1, 384)
        assert len(encoder.calls) == 2
    finally:
        cache.close()


class ShadeEncoder(FakeEncoder):
    """Describe a crop by its mean colour, so a mixed coat is a weaker match."""

    def encode(self, images):
        vectors = np.zeros((len(images), 384), dtype=np.float32)
        for row, image in enumerate(images):
            vectors[row, :3] = image.mean(axis=(0, 1))
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def test_confirmed_name_is_held_through_a_weaker_crop_until_another_animal_claims_it(
    environment, tmp_path
):
    _, catalog, _, _ = environment
    cache = EmbeddingCache(tmp_path / "shades.sqlite")
    identifier = GalleryIdentifier(
        IdentityConfig(labels=("cow",), min_crop_size=32, min_margin=0.4, hold=10),
        catalog,
        partial(prepare_gallery, store=catalog, encoder=ShadeEncoder(), cache=cache),
        ImmediateExecutor(),
    )
    mixed = (200, 130, 0)
    try:
        for second in range(3):
            confirmed = identifier.identify("camera", observation(second, cow()))
        assert confirmed.boxes[0].identity.identity_id == BELLA

        held = identifier.identify("camera", observation(3, cow(color=mixed)))
        assert held.boxes[0].identity.identity_id == BELLA
        assert held.boxes[0].identity.similarity == pytest.approx(0.838, abs=0.001)

        contested = identifier.identify(
            "camera",
            observation(
                4, cow(color=mixed), cow(track=8, coordinates=(70, 10, 110, 50))
            ),
        )
        assert contested.boxes[0].identity.identity_id is None
        assert contested.boxes[1].identity.identity_id is None
    finally:
        cache.close()


class LightnessEncoder:
    """Tells subjects apart by how light they are, as an infrared picture allows."""

    dimension = 2
    fingerprint = "lightness-v1"

    def encode(self, images):
        angles = np.array([image.mean() / 255 * np.pi / 2 for image in images])
        return np.stack([np.cos(angles), np.sin(angles)], axis=1).astype(np.float32)


def test_an_infrared_picture_needs_a_closer_match_than_a_daylight_one(tmp_path):
    catalog = IdentityCatalog(tmp_path / "identities")
    dark, light = (
        catalog.save_sighting(
            np.full((40, 40, 3), shade, dtype=np.uint8),
            "enrollment",
            START,
            index,
            IdentityMatch(),
        )
        for index, shade in enumerate((40, 220))
    )
    write_gallery(
        catalog.directory,
        1,
        [
            {"id": BELLA, "name": "Bella", "samples": [dark]},
            {"id": DAISY, "name": "Daisy", "samples": [light]},
        ],
    )
    cache = EmbeddingCache(tmp_path / "lightness.sqlite")
    identifier = GalleryIdentifier(
        IdentityConfig(
            labels=("cow",),
            min_crop_size=32,
            min_similarity=0.9,
            min_similarity_infrared=0.99,
        ),
        catalog,
        partial(
            prepare_gallery, store=catalog, encoder=LightnessEncoder(), cache=cache
        ),
        ImmediateExecutor(),
    )
    # A little lighter than Bella's photograph: 0.98 similar to it.
    lighter = cow(color=(70, 70, 70))

    def by_day(second):
        seen = observation(second, lighter)
        seen.image[150:, :] = (0, 160, 255)  # straw
        return seen

    try:
        for second in range(3):
            night = identifier.identify("camera", observation(second, lighter))
            assert night.boxes[0].identity.identity_id is None
        assert night.boxes[0].identity.similarity == pytest.approx(0.983, abs=0.001)

        for second in range(3, 6):
            day = identifier.identify("camera", by_day(second))
        assert day.boxes[0].identity.identity_id == BELLA
    finally:
        cache.close()


def test_first_enrollment_collects_photos_without_downloading_a_model(tmp_path):
    loads = []

    def load():
        loads.append(True)
        return FakeEncoder()

    catalog = IdentityCatalog(tmp_path / "identities")
    cache = EmbeddingCache(tmp_path / "embeddings.sqlite")
    identifier = GalleryIdentifier(
        IdentityConfig(labels=("cow",), min_crop_size=32),
        catalog,
        partial(
            prepare_gallery,
            store=catalog,
            encoder=DeferredEncoder(384, load),
            cache=cache,
        ),
        ImmediateExecutor(),
    )
    try:
        result = identifier.identify("camera", observation(0, cow()))
        assert result.boxes[0].identity.identity_id is None
        samples = list((catalog.directory / "sightings").glob("*.json"))
        assert len(samples) == 1
        write_gallery(
            catalog.directory,
            1,
            [
                {"id": BELLA, "name": "Bella", "samples": [samples[0].stem]},
                {"id": DAISY, "name": "Daisy", "samples": []},
            ],
        )
        identifier.identify("camera", observation(1, cow()))
        assert loads == []
        assert not (tmp_path / "embeddings.sqlite").exists()
        second = catalog.save_sighting(
            np.full((40, 40, 3), GREEN, dtype=np.uint8),
            "enrollment",
            START,
            8,
            IdentityMatch(),
        )
        write_gallery(
            catalog.directory,
            2,
            [
                {"id": BELLA, "name": "Bella", "samples": [samples[0].stem]},
                {"id": DAISY, "name": "Daisy", "samples": [second]},
            ],
        )
        for at in (2, 3, 4):
            result = identifier.identify("camera", observation(at, cow()))
        assert loads == [True]
        assert result.boxes[0].identity.identity_id == BELLA
    finally:
        cache.close()


def test_broken_gallery_suppresses_names_and_recovers_without_stopping_detection(
    environment,
    caplog,
):
    identifier, catalog, encoder, identities = environment
    statuses = []
    identifier.report_status = statuses.append
    clock = [0.0]
    identifier.clock = lambda: clock[0]
    for at in range(3):
        identifier.identify("camera", observation(at, cow()))
    (catalog.directory / "catalog.json").write_text("broken JSON")

    original = observation(3, cow())
    assert identifier.identify("camera", original) is original
    assert "Identification unavailable" in caplog.text
    assert statuses[-1].kind == "identity_failed"
    calls = len(encoder.calls)
    write_gallery(catalog.directory, 2, identities)
    assert (
        identifier.identify("camera", observation(10000, cow())).boxes[0].identity
        is None
    )
    assert len(encoder.calls) == calls
    clock[0] = 60.0
    for at in (63, 64):
        assert (
            identifier.identify("camera", observation(at, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    assert (
        identifier.identify("camera", observation(65, cow()))
        .boxes[0]
        .identity.identity_id
        == BELLA
    )
    assert statuses[-1].kind == "identity_ready"


def test_gallery_preparation_is_bounded_and_cannot_publish_a_stale_revision(
    environment,
):
    original, catalog, encoder, identities = environment
    executor = ManualExecutor()
    statuses = []
    identifier = GalleryIdentifier(
        original.settings,
        catalog,
        original.prepare,
        executor,
        report_status=statuses.append,
    )
    for at in range(3):
        assert (
            identifier.identify("camera", observation(at, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    assert len(executor.pending) == 1
    assert encoder.calls == []
    assert statuses[-1].kind == "identity_preparing"
    corrected = [
        {**identities[0], "samples": identities[1]["samples"]},
        {**identities[1], "samples": identities[0]["samples"]},
    ]
    write_gallery(catalog.directory, 2, corrected)
    identifier.identify("camera", observation(3, cow()))
    assert len(executor.pending) == 1
    executor.finish_next()
    identifier.identify("camera", observation(4, cow()))
    assert len(executor.pending) == 1
    assert all(status.kind != "identity_ready" for status in statuses)
    executor.finish_next()
    for at in (5, 6):
        assert (
            identifier.identify("camera", observation(at, cow()))
            .boxes[0]
            .identity.identity_id
            is None
        )
    result = identifier.identify("camera", observation(7, cow()))
    assert result.boxes[0].identity.identity_id == DAISY
    assert statuses[-1].kind == "identity_ready"
    assert executor.pending == []


def test_missing_reference_from_obsolete_preparation_does_not_suspend_new_herd(
    environment,
):
    original, catalog, encoder, identities = environment
    executor = ManualExecutor()
    statuses = []
    identifier = GalleryIdentifier(
        original.settings,
        catalog,
        original.prepare,
        executor,
        report_status=statuses.append,
    )
    identifier.identify("camera", observation(0, cow()))
    (catalog.directory / "images" / f"{identities[0]['samples'][0]}.jpg").unlink()
    write_gallery(catalog.directory, 2, identities[1:])
    executor.finish_next()
    result = identifier.identify("camera", observation(1, cow()))
    assert result.boxes[0].identity.identity_id is None
    assert statuses[-1].kind == "identity_collecting"
    assert all(status.kind != "identity_failed" for status in statuses)
    assert executor.pending == []


def test_accelerator_failure_from_obsolete_preparation_is_still_supervised(environment):
    original, catalog, encoder, identities = environment
    executor = ManualExecutor()
    identifier = GalleryIdentifier(
        original.settings,
        catalog,
        original.prepare,
        executor,
    )
    identifier.identify("camera", observation(0, cow()))
    encoder.failure = True
    write_gallery(catalog.directory, 2, identities[1:])
    executor.finish_next()
    with pytest.raises(RuntimeError, match="Encoder unavailable"):
        identifier.identify("camera", observation(1, cow()))


def test_gallery_preparation_stops_between_encoder_batches(environment, tmp_path):
    _, catalog, _, identities = environment
    stopped = Event()

    class StoppingEncoder(FakeEncoder):
        def encode(self, images):
            result = super().encode(images)
            stopped.set()
            return result

    encoder = StoppingEncoder()
    samples = [
        catalog.save_sighting(
            np.full((40, 40, 3), BLUE, dtype=np.uint8),
            "enrollment",
            START,
            index,
            IdentityMatch(),
        )
        for index in range(9)
    ]
    write_gallery(
        catalog.directory, 2, [{**identities[0], "samples": samples}, identities[1]]
    )
    cache = EmbeddingCache(tmp_path / "stopping.sqlite")
    try:
        with pytest.raises(CancelledError, match="preparation stopped"):
            prepare_gallery(
                catalog.load(), stopped, store=catalog, encoder=encoder, cache=cache
            )
    finally:
        cache.close()
    assert len(encoder.calls) == 1


def test_invalid_cached_vector_is_an_observable_storage_failure(tmp_path):
    cache_path = tmp_path / "embeddings.sqlite"
    encoder = FakeEncoder()
    image = np.full((40, 40, 3), BLUE, dtype=np.uint8)
    cache = EmbeddingCache(cache_path)
    try:
        cache.encode(encoder, [image])
        with sqlite3.connect(cache_path) as database:
            database.execute("UPDATE embeddings SET vector = ?", (b"broken",))
        with pytest.raises(sqlite3.DataError, match="invalid vector size"):
            cache.encode(encoder, [image])
    finally:
        cache.close()


def test_native_model_transfer_failure_is_limited_to_the_download_boundary(
    tmp_path, monkeypatch
):
    import huggingface_hub

    failure = RuntimeError("Native transfer failed")

    def failed_transfer(*args, **kwargs):
        raise failure

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", failed_transfer)
    with pytest.raises(OSError, match="Identity model download failed") as caught:
        download_identity_asset(
            "example/public", "model.safetensors", "pinned", tmp_path
        )
    assert caught.value.__cause__ is failure
