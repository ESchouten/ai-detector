from concurrent.futures import CancelledError
from datetime import datetime
from threading import Event

import numpy as np
import pytest
import torch
from safetensors.torch import save_file

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.herd_gallery import prepare_herd
from aidetector.adapters.inference.herd_model import (
    AnimalNetwork,
    CattleNetwork,
    to_tensor,
)
from aidetector.adapters.inference.identity_observations import (
    distinct_identity_scores,
)
from aidetector.adapters.inference.miewid import MiewidNetwork
from aidetector.domain.models import IdentityMatch

BELLA, DAISY = "a" * 32, "b" * 32
BLUE, GREEN = (230, 40, 20), (20, 230, 40)
# Enough for two plainly different coats, and quick on a processor.
LEARNING = {"members": 2, "minimum_draws": 32}


def photograph(color, seed):
    """A coat of one dominant colour with its own speckles."""
    noise = np.random.default_rng(seed).integers(0, 40, (64, 96, 3))
    return np.clip(np.array(color) + noise, 0, 255).astype(np.uint8)


@pytest.fixture(autouse=True)
def small_and_quick(monkeypatch):
    monkeypatch.setattr(CattleNetwork, "batch", 4)
    monkeypatch.setattr(AnimalNetwork, "batch", 4)
    monkeypatch.setattr(AnimalNetwork, "size", 64)


@pytest.fixture(scope="module")
def starts(tmp_path_factory):
    """Starting weights as the application fetches them, here untaught."""
    torch.manual_seed(0)
    directory = tmp_path_factory.mktemp("weights")
    cattle = CattleNetwork(1).state_dict()
    del cattle["directions"]
    save_file(cattle, str(directory / "cattle.safetensors"))
    save_file(MiewidNetwork().state_dict(), str(directory / "animal.safetensors"))
    return directory / "cattle.safetensors", directory / "animal.safetensors"


def confirm(store, revision, herd):
    catalog = Catalog.model_validate({"revision": revision, "identities": herd})
    store.directory.mkdir(parents=True, exist_ok=True)
    (store.directory / "catalog.json").write_text(catalog.model_dump_json())
    return store.load()


@pytest.fixture
def herd(tmp_path):
    store = IdentityCatalog(tmp_path / "identities")
    photographs = {
        name: [
            store.save_sighting(
                photograph(color, seed),
                "camera",
                datetime(2026, 1, 1),
                1,
                IdentityMatch(),
            )
            for seed in range(4)
        ]
        for name, color in (("Bella", BLUE), ("Daisy", GREEN))
    }
    identities = [
        {"id": BELLA, "name": "Bella", "samples": photographs["Bella"]},
        {"id": DAISY, "name": "Daisy", "samples": photographs["Daisy"]},
    ]
    return store, identities


def prepare(store, catalog, starts, tmp_path, stopped=None):
    cattle, animal = starts
    return prepare_herd(
        catalog,
        stopped,
        store=store,
        cattle_start=cattle,
        animal_start=animal,
        directory=tmp_path / "herd",
        **LEARNING,
    )


def test_learning_the_confirmed_photographs_tells_new_crops_apart(
    herd, starts, tmp_path
):
    store, identities = herd
    gallery = prepare(store, confirm(store, 1, identities), starts, tmp_path)

    # Every confirmed photograph is a reference of its cow.
    assert gallery.owners == ((BELLA, "Bella"),) * 4 + ((DAISY, "Daisy"),) * 4
    assert gallery.neighbours == 2
    # One part for the two cattle networks, scaled so that a dot product is
    # their mean, and one for the animal network.
    assert gallery.parts == (2 * 256, 2152)
    assert gallery.vectors.shape == (8, 2 * 256 + 2152)
    described = gallery.encoder.encode([photograph(BLUE, 90), photograph(GREEN, 91)])
    for vectors in (gallery.vectors, described):
        for part in (vectors[:, :512], vectors[:, 512:]):
            np.testing.assert_allclose(np.linalg.norm(part, axis=1), 1, atol=1e-5)
    best = [
        max(scores, key=lambda score: score.similarity).name
        for scores in distinct_identity_scores(
            described,
            gallery.vectors,
            gallery.owners,
            gallery.neighbours,
            gallery.parts,
        )
    ]
    assert best == ["Bella", "Daisy"]
    assert gallery.encoder.encode([]).shape == (0, 2 * 256 + 2152)


def test_a_network_sees_how_light_a_coat_is_and_not_its_colour():
    grey = np.full((8, 8, 3), 100, dtype=np.uint8)
    red = np.full((8, 8, 3), (47, 100, 120), dtype=np.uint8)
    darker = np.full((8, 8, 3), 60, dtype=np.uint8)

    seen = to_tensor([grey, red, darker])

    torch.testing.assert_close(seen[0], seen[1], atol=0.01, rtol=0)
    assert (seen[0] - seen[2]).abs().min() > 0.5


def test_an_unchanged_herd_is_reloaded_and_a_renamed_cow_keeps_its_model(
    herd, starts, tmp_path
):
    store, identities = herd
    learned = prepare(store, confirm(store, 1, identities), starts, tmp_path)
    for image in (store.directory / "images").glob("*.jpg"):
        image.unlink()

    renamed = [{**identities[0], "name": "Bella 2"}, identities[1]]
    reloaded = prepare(store, confirm(store, 2, renamed), starts, tmp_path)

    assert reloaded.owners == ((BELLA, "Bella 2"),) * 4 + ((DAISY, "Daisy"),) * 4
    np.testing.assert_allclose(reloaded.vectors, learned.vectors, atol=1e-6)


def test_a_changed_set_of_photographs_is_learned_again(herd, starts, tmp_path):
    store, identities = herd
    prepare(store, confirm(store, 1, identities), starts, tmp_path)
    for image in (store.directory / "images").glob("*.jpg"):
        image.unlink()

    fewer = [{**identities[0], "samples": identities[0]["samples"][:3]}, identities[1]]
    with pytest.raises(OSError, match="missing or unreadable"):
        prepare(store, confirm(store, 2, fewer), starts, tmp_path)


def test_cows_without_photographs_are_not_taught(herd, starts, tmp_path):
    store, identities = herd
    molly = {"id": "c" * 32, "name": "Molly", "samples": []}
    gallery = prepare(store, confirm(store, 1, [*identities, molly]), starts, tmp_path)

    assert {name for _, name in gallery.owners} == {"Bella", "Daisy"}


def test_learning_stops_when_the_application_shuts_down(herd, starts, tmp_path):
    store, identities = herd
    stopped = Event()
    stopped.set()
    with pytest.raises(CancelledError, match="Herd learning stopped"):
        prepare(store, confirm(store, 1, identities), starts, tmp_path, stopped)
    assert not (tmp_path / "herd" / "herd.json").exists()
