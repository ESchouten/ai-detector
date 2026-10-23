import json
from datetime import datetime

import cv2
import numpy as np
import pytest

from aidetector.adapters.individuals import herd as herd_module
from aidetector.adapters.individuals.embedding import EmbeddingModel, model_key
from aidetector.adapters.individuals.herd import Herd, TrackIdentifier
from aidetector.adapters.individuals.records import GroupsFile, SightingRecord
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


def groups(herd):
    herd.flush()
    return GroupsFile.model_validate_json(
        (herd.directory / "groups.json").read_text()
    ).groups


def test_unnamed_look_alike_sightings_are_grouped_for_naming(tmp_path):
    herd = herd_of(tmp_path)
    sightings: dict[str, list[str]] = {}
    for day in (1, 2):
        for individual in TrackIdentifier(herd).identify(
            event(day, whole_herd()), "e" * 32
        ):
            coat = list(COATS)[individual.track_id - 1]
            sightings.setdefault(coat, []).append(individual.sighting)
    assert sorted(sorted(g.sightings) for g in groups(herd)) == sorted(
        sorted(both) for both in sightings.values()
    )
    assert all(g.suggestions == [] for g in groups(herd))

    name(herd, {sightings["412"][0]: "412", sightings["233"][0]: "233"})
    later = TrackIdentifier(herd).identify(event(3, [(1, "412", PLACES[0])]), "a" * 32)
    listed = groups(herd)
    named = {sightings["412"][0], sightings["233"][0]}
    assert not any(named & set(g.sightings) for g in listed)
    joined = next(g for g in listed if later[0].sighting in g.sightings)
    assert sorted(joined.sightings) == sorted([sightings["412"][1], later[0].sighting])
    assert [suggestion.name for suggestion in joined.suggestions] == ["412", "233"]


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
    known = other.known()
    assert known.gallery.names == ("412",)
    assert known.threshold is None
    assert (other.sightings / sighting / f"vectors-{other.model.key}.npy").exists()


def test_only_tracked_boxes_of_the_configured_classes_large_enough_count(tmp_path):
    identifier = TrackIdentifier(herd_of(tmp_path))
    assert identifier.identify(event(1, [(None, "412", PLACES[0])]), "e" * 32) == ()
    assert (
        identifier.identify(event(1, [(1, "412", PLACES[0])], label="person"), "e" * 32)
        == ()
    )
    assert identifier.identify(event(1, [(1, "412", (20, 40, 60, 80))]), "e" * 32) == ()


def pictures(herd, individual):
    folder = herd.sightings / individual.sighting
    return [
        cv2.imread(str(folder / f"crop-{index}.jpg"))
        for index in range(1, len(list(folder.glob("crop-*.jpg"))) + 1)
    ]


def test_whole_uncovered_pictures_are_chosen_before_larger_cut_off_ones(tmp_path):
    herd = herd_of(tmp_path)
    cut_off = observation(1, 0, [(1, "412", (0, 40, 150, 200))])
    covered = observation(
        1, 1, [(1, "412", (100, 40, 220, 160)), (2, "233", (90, 30, 200, 150))]
    )
    whole = observation(1, 2, [(1, "412", (100, 40, 160, 100))])
    [individual, _] = TrackIdentifier(herd).identify(
        DetectionEvent(SOURCE, (cut_off, covered, whole)), "e" * 32
    )
    assert [picture.shape for picture in pictures(herd, individual)] == [
        (60, 60, 3),
        (160, 150, 3),
        (120, 120, 3),
    ]


def test_outside_a_segmentation_outline_pictures_are_grey(tmp_path):
    herd = herd_of(tmp_path)
    image = np.full((240, 320, 3), 128, np.uint8)
    image[40:100, 100:130] = COATS["412"]
    image[40:100, 130:160] = COATS["233"]
    # The box holds both coats; the outline only the first.
    outline = ((100, 40), (129, 40), (129, 99), (100, 99))
    box = BoundingBox(100, 40, 160, 100, "cow", 0.9, 1, outline)
    seen = Observation(datetime(2026, 10, 1), image, {"cow": 0.9}, (box,))

    [individual] = TrackIdentifier(herd).identify(
        DetectionEvent(SOURCE, (seen,)), "e" * 32
    )

    [picture] = pictures(herd, individual)
    assert picture.shape == (60, 60, 3)
    # JPEG blurs the edge between the halves; their middles keep their colour.
    assert np.abs(picture[30, 10].astype(int) - COATS["412"]).max() < 12
    assert np.abs(picture[30, 50].astype(int) - 127).max() < 12
    assert image[50, 140].tolist() == list(COATS["233"])


def watch(identifier, seconds, cows, start=0):
    """Observe cows once a second, as live detection does."""
    for second in range(start, start + seconds):
        identifier.observe(SOURCE, observation(1, second, cows))


def test_a_track_watched_live_is_saved_in_the_background_and_named_at_once(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(herd_module, "LOOKING", 0)
    herd = herd_of(tmp_path)
    identifier = TrackIdentifier(herd)
    watch(identifier, 3, [(1, "412", PLACES[0])])
    herd.flush()
    assert identifier.identity(SOURCE, 1) is None
    assert not herd.sightings.exists()

    watch(identifier, 3, [(1, "412", PLACES[0])], start=3)
    herd.flush()
    unnamed = identifier.identity(SOURCE, 1)
    assert unnamed is not None
    assert (unnamed.track_id, unnamed.name, unnamed.candidates) == (1, None, ())
    record = SightingRecord.model_validate_json(
        (herd.sightings / unnamed.sighting / "sighting.json").read_text()
    )
    assert (record.seen, record.event_id, record.crops) == (
        "2026-10-01T12:00:00",
        None,
        4,
    )
    assert identifier.identity(SOURCE, 2) is None

    # One day of names would only suggest; a person's own name for it shows at once.
    name(herd, {unnamed.sighting: "412"})
    named = identifier.identity(SOURCE, 1)
    assert named is not None
    assert (named.sighting, named.name) == (unnamed.sighting, "412")

    # The event the track was in keeps its sighting.
    [individual] = identifier.identify(event(1, [(1, "412", PLACES[0])]), "e" * 32)
    assert (individual.sighting, individual.name) == (unnamed.sighting, "412")
    assert (
        len([path for path in herd.sightings.iterdir() if path.name != ".pending"]) == 1
    )


def test_a_track_coming_in_from_the_edge_waits_for_a_whole_picture(tmp_path):
    herd = herd_of(tmp_path)
    identifier = TrackIdentifier(herd)
    watch(identifier, 6, [(1, "412", (0, 40, 60, 100))])
    herd.flush()
    assert identifier.identity(SOURCE, 1) is None

    watch(identifier, 1, [(1, "412", PLACES[0])], start=6)
    herd.flush()
    saved = identifier.identity(SOURCE, 1)
    assert saved is not None
    assert [picture.shape for picture in pictures(herd, saved)][0] == (60, 60, 3)

    # One that never shows whole is saved after a while all the same.
    watch(identifier, 16, [(2, "233", (0, 40, 60, 100))], start=7)
    herd.flush()
    assert identifier.identity(SOURCE, 2) is not None


def test_a_track_gone_before_it_settled_is_saved_with_what_was_seen(tmp_path):
    herd = herd_of(tmp_path)
    identifier = TrackIdentifier(herd)
    watch(identifier, 2, [(1, "412", PLACES[0])])
    watch(identifier, 10, [(2, "233", PLACES[1])], start=2)
    herd.flush()
    gone = identifier.identity(SOURCE, 1)
    assert gone is not None
    assert len(pictures(herd, gone)) == 2


def test_only_the_latest_unnamed_sightings_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(herd_module, "KEPT_MAX", 2)
    herd = herd_of(tmp_path)
    identifier = TrackIdentifier(herd)
    oldest, older, newer, newest = (
        identifier.identify(event(day, [(day, "412", PLACES[0])]), "e" * 32)[0]
        for day in (1, 2, 3, 4)
    )
    name(herd, {oldest.sighting: "412"})
    groups(herd)
    assert sorted(path.name for path in herd.sightings.iterdir()) == sorted(
        [".pending", oldest.sighting, newer.sighting, newest.sighting]
    )
    assert older.sighting not in {s for g in groups(herd) for s in g.sightings}
