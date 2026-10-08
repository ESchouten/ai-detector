import json
import sys
from pathlib import Path

import cv2
import numpy as np

from app_score import preset_rules
from enroll import write_herd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

from aidetector.adapters.identity_catalog import IdentityCatalog


def test_publisher_crops_become_a_herd_the_application_can_read(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    rows = []
    for cow, shade in ((5, 40), (5, 80), (9, 200)):
        name = f"{cow}-{shade}.png"
        cv2.imwrite(str(crops / name), np.full((30, 40, 3), shade, dtype=np.uint8))
        rows.append({"path": name, "cow": cow})

    identities = write_herd(rows, crops, tmp_path / "data")

    store = IdentityCatalog(tmp_path / "data" / "identities")
    catalog = store.load()
    assert [(cow.name, len(cow.samples)) for cow in catalog.identities] == [("5", 2), ("9", 1)]
    assert {cow.id for cow in catalog.identities} == set(identities.values())
    assert store.read_image(catalog.identities[1].samples[0]).shape == (30, 40, 3)


def test_replay_rules_are_the_shipped_preset():
    preset = json.loads(
        (Path(__file__).resolve().parents[3] / "config" / "detector" / "cow-identity.json").read_text()
    )
    rules = preset_rules(preset)
    identity = preset["identity"]
    assert (
        rules.min_similarity,
        rules.min_similarity_infrared,
        rules.min_margin,
        rules.min_observations,
        rules.hold,
    ) == (
        identity["min_similarity"],
        identity["min_similarity_infrared"],
        identity["min_margin"],
        identity["min_observations"],
        identity["hold"],
    )
    # The application always refuses boxes at the picture's edge, and keeps a
    # briefly missed track's agreement.
    assert rules.whole_animal and not rules.forget_absent
