import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.domain.models import IdentityMatch

NOW = datetime(2026, 1, 1)
IMAGE = np.full((40, 48, 3), (20, 100, 200), dtype=np.uint8)


def write_catalog(directory, revision, identities):
    content = Catalog.model_validate({"revision": revision, "identities": identities})
    directory.mkdir(parents=True, exist_ok=True)
    pending = directory / "catalog.tmp"
    pending.write_text(content.model_dump_json(), encoding="utf-8")
    pending.replace(directory / "catalog.json")


def test_sighting_is_reviewable_evidence_and_never_enrolls_a_prediction(tmp_path):
    catalog = IdentityCatalog(tmp_path)
    assert catalog.load() == Catalog()
    assert not (tmp_path / "catalog.json").exists()
    source = "rtsp://user:secret@camera/live"

    sample = catalog.save_sighting(
        IMAGE, source, NOW, 7, IdentityMatch("a" * 32, "Bella", 0.95)
    )
    record = json.loads((tmp_path / "sightings" / f"{sample}.json").read_text())

    assert record["id"] == record["image"] == sample
    assert record["source"] == hashlib.sha256(source.encode()).hexdigest()
    assert record["captured_at"] == NOW.isoformat()
    assert record["track_id"] == 7
    assert record["identity"] == {
        "id": "a" * 32,
        "name": "Bella",
        "similarity": 0.95,
    }
    assert "secret" not in json.dumps(record)
    assert catalog.read_image(sample).shape == IMAGE.shape
    assert catalog.load().identities == ()
    assert not (tmp_path / "catalog.json").exists()
    assert not list((tmp_path / "sightings").glob("*.tmp"))


def test_pending_limit_counts_only_unassigned_examples_and_recovers_after_review(
    tmp_path,
):
    catalog = IdentityCatalog(tmp_path, max_pending=2)
    first = catalog.save_sighting(IMAGE, "camera", NOW, 1, IdentityMatch())
    second = catalog.save_sighting(IMAGE, "camera", NOW, 2, IdentityMatch())

    assert catalog.save_sighting(IMAGE, "camera", NOW, 3, IdentityMatch()) is None
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 2
    write_catalog(tmp_path, 1, [{"id": "a" * 32, "name": "Bella", "samples": [first]}])
    before = (tmp_path / "catalog.json").read_bytes()

    third = catalog.save_sighting(IMAGE, "camera", NOW, 3, IdentityMatch())

    assert third not in (None, first, second)
    assert catalog.save_sighting(IMAGE, "camera", NOW, 4, IdentityMatch()) is None
    assert len(list((tmp_path / "sightings").glob("*.json"))) == 3
    assert (tmp_path / "catalog.json").read_bytes() == before


def test_live_catalog_reads_corrections_and_removal_without_altering_evidence(tmp_path):
    catalog = IdentityCatalog(tmp_path)
    sample = catalog.save_sighting(IMAGE, "camera", NOW, 7, IdentityMatch())
    evidence = (tmp_path / "images" / f"{sample}.jpg").read_bytes()
    write_catalog(tmp_path, 1, [{"id": "a" * 32, "name": "Bella", "samples": [sample]}])
    assert catalog.load().identities[0].name == "Bella"
    write_catalog(tmp_path, 2, [{"id": "b" * 32, "name": "Daisy", "samples": [sample]}])

    corrected = catalog.load()
    assert corrected.revision == 2
    assert corrected.identities[0].id == "b" * 32
    assert corrected.identities[0].name == "Daisy"
    assert (tmp_path / "images" / f"{sample}.jpg").read_bytes() == evidence
    (tmp_path / "catalog.json").unlink()
    assert catalog.load() == Catalog()


def test_sighting_keeps_the_inference_revision_when_gallery_changes_before_save(
    tmp_path,
):
    catalog = IdentityCatalog(tmp_path)
    write_catalog(tmp_path, 2, [])

    sample = catalog.save_sighting(
        IMAGE,
        "camera",
        NOW,
        7,
        IdentityMatch("a" * 32, "Bella", 0.95),
        gallery_revision=1,
    )

    record = json.loads((tmp_path / "sightings" / f"{sample}.json").read_text())
    assert record["gallery_revision"] == 1
    assert catalog.load().revision == 2


@pytest.mark.parametrize(
    "second",
    [
        {"id": "a" * 32, "name": "Daisy", "samples": ["d" * 32]},
        {"id": "b" * 32, "name": " bella ", "samples": ["d" * 32]},
        {"id": "b" * 32, "name": "Daisy", "samples": ["c" * 32]},
    ],
)
def test_catalog_rejects_duplicate_identity_name_or_reference_assignment(
    tmp_path, second
):
    (tmp_path / "catalog.json").write_text(
        json.dumps(
            {
                "identities": [
                    {"id": "a" * 32, "name": "Bella", "samples": ["c" * 32]},
                    second,
                ]
            }
        )
    )
    with pytest.raises(ValidationError, match="must be unique"):
        IdentityCatalog(tmp_path).load()


def test_malformed_catalog_and_missing_image_remain_visible_failures(tmp_path):
    catalog = IdentityCatalog(tmp_path)
    (tmp_path / "catalog.json").write_text("not json")
    with pytest.raises(ValidationError):
        catalog.load()
    with pytest.raises(ValueError, match="missing or unreadable"):
        catalog.read_image("a" * 32)


def test_failed_sighting_publication_leaves_no_orphan_image(tmp_path, monkeypatch):
    def cannot_publish(self, target):
        raise OSError("Disk unavailable")

    monkeypatch.setattr(Path, "replace", cannot_publish)
    with pytest.raises(OSError, match="Disk unavailable"):
        IdentityCatalog(tmp_path).save_sighting(
            IMAGE, "camera", NOW, 7, IdentityMatch()
        )

    assert list((tmp_path / "images").iterdir()) == []
    assert list((tmp_path / "sightings").iterdir()) == []


def test_interrupted_image_write_is_removed_before_a_later_retry(tmp_path, monkeypatch):
    write_bytes = Path.write_bytes

    def disk_full(self, content):
        write_bytes(self, content[:20])
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "write_bytes", disk_full)
    with pytest.raises(OSError, match="No space left"):
        IdentityCatalog(tmp_path).save_sighting(
            IMAGE, "camera", NOW, 7, IdentityMatch()
        )

    assert list((tmp_path / "images").iterdir()) == []
    assert list((tmp_path / "sightings").iterdir()) == []
