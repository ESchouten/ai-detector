"""Prepare an immutable gallery away from the camera-processing thread."""

from concurrent.futures import CancelledError
from dataclasses import dataclass
from threading import Event

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.identity import EmbeddingCache, ImageEncoder


@dataclass(frozen=True)
class PreparedGallery:
    catalog: Catalog
    vectors: NDArray[np.float32]
    owners: tuple[tuple[str, str], ...]


def prepare_gallery(
    catalog: Catalog,
    store: IdentityCatalog,
    encoder: ImageEncoder,
    cache: EmbeddingCache,
    stopped: Event | None = None,
) -> PreparedGallery:
    samples = [(cow, sample) for cow in catalog.identities for sample in cow.samples]
    batches = []
    for start in range(0, len(samples), 8):
        if stopped is not None and stopped.is_set():
            raise CancelledError("Identity gallery preparation stopped")
        batches.append(
            cache.encode(
                encoder,
                [store.read_image(sample) for _, sample in samples[start : start + 8]],
            )
        )
    return PreparedGallery(
        catalog,
        np.concatenate(batches),
        tuple((cow.id, cow.name) for cow, _ in samples),
    )
