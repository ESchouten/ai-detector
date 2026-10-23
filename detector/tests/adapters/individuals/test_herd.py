import json
from datetime import datetime

import numpy as np
import pytest

from aidetector.adapters.individuals.embedding import EmbeddingModel, model_key
from aidetector.adapters.individuals.herd import Herd, TrackIdentifier, track_crops
from aidetector.adapters.individuals.records import SightingRecord
from aidetector.application.ports import IdentificationUnavailable, camera_id
from aidetector.configuration import IndividualsConfig
from aidetector.domain.models import BoundingBox, DetectionEvent, Observation
from tests.support.onnx_model import write_embedding_model

SOURCE = "rtsp://camera.invalid/stream"
# BGR coat colours stand in for coat patterns: the test model embeds mean colour.
COATS = {"412": (0, 0, 255), "233": (0, 255, 0), "87": (255, 0, 0), "15": (0, 255, 255)}
PLACES = [
    (20, 40, 80, 100),
    (100, 40, 160, 100),
    (180, 40, 240, 100),
    (250, 40, 310, 100),
]


def observation(day, second, cows, label="cow"):
    image = np.full((240, 320, 3), 128, np.uint8)
    boxes = []
    for track, coat, (x1, y1, x2, y2) in cows:
        image[y1:y2, x1:x2] = COATS[coat]
        boxes.append(BoundingBox(x1, y1, x2, y2, label, 0.9, track))
    return Observation(
        datetime(2026, 10, day, 12, 0, second), image, {"cow": 0.9}, tuple(boxes)
    )


def event(day, cows, frames=3, label="cow"):
    return DetectionEvent(
        SOURCE, tuple(observation(day, second, cows, label) for second in range(frames))
    )


def herd_of(tmp_path, metadata=None):
    path = tmp_path / ("model.onnx" if metadata is None else "other.onnx")
    write_embedding_model(path, metadata=metadata)
    model = EmbeddingModel(str(path), model_key(str(path)))
    return Herd(
        tmp_path / "individuals",
        model,
        IndividualsConfig(model=str(path), labels="cow"),
    )


def name(herd, names):
    (herd.directory / "names.json").write_text(
        json.dumps({"version": 1, "names": names}), encoding="utf-8"
    )


def whole_herd():
    return [(track, coat, PLACES[track - 1]) for track, coat in enumerate(COATS, 1)]


def test_tracked_individuals_are_kept_as_sightings_until_someone_names_them(tmp_path):
    herd = herd_of(tmp_path)
    identifier = TrackIdentifier(herd)
    individuals = identifier.identify(
        event(1, [(1, "412", PLACES[0]), (2, "233", PLACES[1])]), "e" * 32
    )
    assert [(i.track_id, i.label, i.candidates, i.name) for i in individuals] == [
        (1, "cow", (), None),
        (2, "cow", (), None),
    ]
    folder = herd.sightings / individuals[0].sighting
    record = SightingRecord.model_validate_json((folder / "sighting.json").read_text())
    assert record.camera == camera_id(SOURCE)
    assert (record.track, record.event_id, record.seen) == (
        1,
        "e" * 32,
        "2026-10-01T12:00:00",
    )
    assert sorted(path.name for path in folder.iterdir()) == [
        "crop-1.jpg",
        "crop-2.jpg",
        "crop-3.jpg",
        "sighting.json",
        f"vectors-{herd.model.key}.npy",
    ]

    # A track that continues into the next event keeps its sighting.
    again = identifier.identify(event(1, [(1, "412", PLACES[0])]), "f" * 32)
    assert again[0].sighting == individuals[0].sighting
    assert (
        len([path for path in herd.sightings.iterdir() if path.name != ".pending"]) == 2
    )


def test_names_given_on_two_days_recognise_later_tracks_without_a_restart(tmp_path):
    herd = herd_of(tmp_path)
    named: dict[int, dict[str, str]] = {}
    for day in (1, 2):
        # Each run of a tracker numbers its tracks anew.
        individuals = TrackIdentifier(herd).identify(event(day, whole_herd()), "e" * 32)
        named[day] = {i.sighting: list(COATS)[i.track_id - 1] for i in individuals}

    identifier = TrackIdentifier(herd)
    name(herd, named[1])
    unsure = identifier.identify(event(3, [(9, "412", PLACES[2])]), "a" * 32)[0]
    assert unsure.name is None
    assert [candidate.name for candidate in unsure.candidates][0] == "412"
    assert len(unsure.candidates) == 3

    name(herd, named[1] | named[2])
    sure = identifier.identify(event(3, [(9, "412", PLACES[2])]), "b" * 32)[0]
    assert sure.recognised
    assert sure.name == "412"
    assert sure.sighting == unsure.sighting


def test_invalid_names_make_identification_unavailable(tmp_path):
    herd = herd_of(tmp_path)
    herd.directory.mkdir(parents=True)
    (herd.directory / "names.json").write_text('{"names": {"x": "412"}}')
    with pytest.raises(IdentificationUnavailable, match="invalid"):
        TrackIdentifier(herd).identify(event(1, [(1, "412", PLACES[0])]), "e" * 32)


def test_another_model_embeds_named_sightings_again_from_their_pictures(tmp_path):
    herd = herd_of(tmp_path)
    sighting = (
        TrackIdentifier(herd)
        .identify(event(1, [(1, "412", PLACES[0])]), "e" * 32)[0]
        .sighting
    )
    name(herd, {sighting: "412"})
    other = herd_of(tmp_path, metadata={"mean": "0.5,0.5,0.5", "std": "0.25,0.25,0.25"})
    assert other.model.key != herd.model.key
    gallery, threshold = other.known()
    assert gallery.names == ("412",)
    assert threshold is None
    assert (other.sightings / sighting / f"vectors-{other.model.key}.npy").exists()


def test_only_tracked_boxes_of_the_configured_classes_large_enough_count(tmp_path):
    identifier = TrackIdentifier(herd_of(tmp_path))
    assert identifier.identify(event(1, [(None, "412", PLACES[0])]), "e" * 32) == ()
    assert (
        identifier.identify(event(1, [(1, "412", PLACES[0])], label="person"), "e" * 32)
        == ()
    )
    assert identifier.identify(event(1, [(1, "412", (20, 40, 60, 80))]), "e" * 32) == ()


def test_whole_uncovered_pictures_are_chosen_before_larger_cut_off_ones():
    cut_off = observation(1, 0, [(1, "412", (0, 40, 150, 200))])
    covered = observation(
        1, 1, [(1, "412", (100, 40, 220, 160)), (2, "233", (90, 30, 200, 150))]
    )
    whole = observation(1, 2, [(1, "412", (100, 40, 160, 100))])
    tracks = track_crops(
        DetectionEvent(SOURCE, (cut_off, covered, whole)), frozenset({"cow"}), 1
    )
    label, crops = tracks[1]
    assert label == "cow"
    assert [crop.shape for crop in crops] == [(60, 60, 3)]
