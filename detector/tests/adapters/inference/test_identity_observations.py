import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.identity import EmbeddingCache
from aidetector.adapters.inference.identity_observations import (
    GalleryIdentifier,
    distinct_identity_scores,
    usable_crop,
)
from aidetector.configuration import IdentityConfig
from aidetector.domain.models import BoundingBox, IdentityMatch, Observation

START = datetime(2026, 1, 1)
BELLA, DAISY = "a" * 32, "b" * 32
BLUE, GREEN = (240, 0, 0), (0, 240, 0)


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
        IdentityConfig(labels=("cow",), min_crop_size=32), catalog, encoder, cache
    )
    try:
        yield identifier, catalog, encoder, identities
    finally:
        cache.close()


def observation(second, *subjects):
    image = np.zeros((200, 240, 3), dtype=np.uint8)
    boxes = []
    for track_id, color, coordinates, label in subjects:
        x1, y1, x2, y2 = coordinates
        image[max(0, y1) : min(200, y2), max(0, x1) : min(240, x2)] = color
        boxes.append(BoundingBox(x1, y1, x2, y2, label, 0.95, track_id))
    return Observation(
        START + timedelta(seconds=second), image, {"cow": 0.95}, tuple(boxes)
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


def test_departed_or_reused_track_needs_fresh_agreement(environment):
    identifier, _, _, _ = environment
    for second in range(3):
        identifier.identify("camera", observation(second, cow()))

    assert identifier.identify("camera", observation(2.1)).boxes == ()
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
    assert (
        identifier.identify("camera", observation(11, cow()))
        .boxes[0]
        .identity.identity_id
        is None
    )


def test_live_encoder_failure_does_not_become_an_unknown_identity(environment):
    identifier, catalog, encoder, _ = environment
    identifier.identify("camera", observation(0, cow()))
    evidence_before = set((catalog.directory / "sightings").glob("*.json"))
    encoder.failure = True

    with pytest.raises(RuntimeError, match="Encoder unavailable"):
        identifier.identify("camera", observation(1, cow()))

    assert set((catalog.directory / "sightings").glob("*.json")) == evidence_before


def test_deleted_gallery_image_is_an_explicit_failure_not_an_empty_gallery(environment):
    identifier, catalog, _, identities = environment
    (catalog.directory / "images" / f"{identities[0]['samples'][0]}.jpg").unlink()

    with pytest.raises(ValueError, match="missing or unreadable"):
        identifier.identify("camera", observation(0, cow()))


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
