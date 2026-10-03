"""Shared gallery contract: web owns labels, detector publishes immutable sightings."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidetector.adapters.media.images import encode_jpeg
from aidetector.domain.models import IdentityMatch

Identifier = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
logger = logging.getLogger(__name__)


class EnrolledIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=80)]
    samples: Annotated[tuple[Identifier, ...], Field(max_length=32)]


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    revision: Annotated[int, Field(ge=0)] = 0
    identities: Annotated[tuple[EnrolledIdentity, ...], Field(max_length=500)] = ()

    @model_validator(mode="after")
    def unique_labels_and_samples(self) -> Catalog:
        ids = [item.id for item in self.identities]
        names = [item.name.strip().lower() for item in self.identities]
        samples = [sample for item in self.identities for sample in item.samples]
        if (
            len(set(ids)) != len(ids)
            or len(set(names)) != len(names)
            or "" in names
            or len(set(samples)) != len(samples)
        ):
            raise ValueError(
                "Gallery identities, names and example assignments must be unique"
            )
        return self


class IdentityCatalog:
    """No predicted identity is ever written into the farmer-confirmed catalog."""

    def __init__(self, directory: Path, max_pending: int = 200):
        self.directory = directory
        self.max_pending = max_pending
        self._lock = Lock()
        self._stamp: tuple[int, int] | None = None
        self._catalog = Catalog()
        self._pending_full = False

    def load(self) -> Catalog:
        path = self.directory / "catalog.json"
        with self._lock:
            try:
                stat = path.stat()
            except FileNotFoundError:
                self._stamp = None
                self._catalog = Catalog()
                return self._catalog
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp != self._stamp:
                self._catalog = Catalog.model_validate_json(path.read_bytes())
                self._stamp = stamp
            return self._catalog

    def read_image(self, sample: str) -> NDArray[np.uint8]:
        image = cv2.imread(str(self.directory / "images" / f"{sample}.jpg"))
        if image is None:
            raise OSError(f"Identity example {sample} is missing or unreadable")
        return image

    def save_sighting(
        self,
        image: NDArray[np.uint8],
        source: str,
        at: datetime,
        track_id: int | None,
        match: IdentityMatch,
        *,
        gallery_revision: int | None = None,
    ) -> str | None:
        catalog = self.load()
        enrolled = {sample for item in catalog.identities for sample in item.samples}
        with self._lock:
            sightings = self.directory / "sightings"
            sightings.mkdir(parents=True, exist_ok=True)
            pending = sum(
                file.stem not in enrolled for file in sightings.glob("*.json")
            )
            if pending >= self.max_pending:
                if not self._pending_full:
                    logger.warning(
                        "Herd review queue is full (%d photos); review photos to resume collection. Matching continues.",
                        self.max_pending,
                    )
                    self._pending_full = True
                return None
            if self._pending_full:
                logger.info("Herd photo collection resumed after review")
                self._pending_full = False
            images = self.directory / "images"
            images.mkdir(exist_ok=True)
            sample = uuid4().hex
            record = {
                "version": 1,
                "id": sample,
                "image": sample,
                "source": hashlib.sha256(source.encode()).hexdigest(),
                "captured_at": at.isoformat(),
                "track_id": track_id,
                "gallery_revision": gallery_revision,
                "identity": {
                    "id": match.identity_id,
                    "name": match.name,
                    "similarity": match.similarity,
                },
            }
            temporary = sightings / f"{sample}.tmp"
            try:
                (images / f"{sample}.jpg").write_bytes(encode_jpeg(image, quality=95))
                temporary.write_text(json.dumps(record), encoding="utf-8")
                temporary.replace(sightings / f"{sample}.json")
            except OSError:
                (images / f"{sample}.jpg").unlink(missing_ok=True)
                raise
            finally:
                temporary.unlink(missing_ok=True)
            return sample
