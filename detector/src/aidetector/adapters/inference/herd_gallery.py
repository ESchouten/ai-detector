"""Teach, or reload, the herd's identity model away from the camera thread."""

import hashlib
import json
import logging
from concurrent.futures import CancelledError
from contextlib import nullcontext
from pathlib import Path
from threading import Event

import numpy as np

from aidetector.adapters.identity_catalog import Catalog, IdentityCatalog
from aidetector.adapters.inference.device import mps_inference
from aidetector.adapters.inference.herd_model import (
    MINIMUM_DRAWS,
    AnimalNetwork,
    CattleNetwork,
    HerdEncoder,
    HerdNetwork,
    choose_device,
    learn,
)
from aidetector.adapters.inference.identity_gallery import PreparedGallery

logger = logging.getLogger(__name__)
# Changes whenever learning itself changes, so that saved models are retaught.
RECIPE = "cattle-dinov2-small-224-and-miewid-288-v4"
# Cattle networks, taught in a different order each; one animal network joins them.
MEMBERS = 3
# One odd or wrongly confirmed photograph cannot carry a name on its own.
NEIGHBOURS = 2
# A cow is scored by one in fifty of her photographs, the most similar ones. A
# fixed number would score every animal higher, strangers too, as she gains
# photographs, and the limits would hold for one size of herd only.
SHARE = 0.02


def prepare_herd(
    catalog: Catalog,
    stopped: Event | None = None,
    *,
    store: IdentityCatalog,
    cattle_start: Path,
    animal_start: Path,
    directory: Path,
    members: int = MEMBERS,
    minimum_draws: int = MINIMUM_DRAWS,
) -> PreparedGallery:
    """The confirmed photographs, described by networks taught to tell them apart.

    Learning takes minutes, so the networks and the descriptions are kept on
    disk and reused for as long as the confirmed photographs and the starting
    weights stay the same.
    """
    from safetensors.torch import load_file, save_file

    cows = [cow for cow in catalog.identities if cow.samples]
    digest = hashlib.sha256(f"{RECIPE}:{members}".encode())
    for start in (cattle_start, animal_start):
        with start.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    for cow in cows:
        digest.update(f"{cow.id}:{','.join(cow.samples)}\n".encode())
    fingerprint = digest.hexdigest()
    record = directory / "herd.json"
    described = directory / "herd-photographs.npy"
    # Each network with its saved file and the weights it starts from.
    taught: list[tuple[HerdNetwork, Path, Path]] = [
        (
            CattleNetwork(len(cows)),
            directory / f"herd-cattle-{member}.safetensors",
            cattle_start,
        )
        for member in range(members)
    ]
    taught.append(
        (AnimalNetwork(len(cows)), directory / "herd-animal.safetensors", animal_start)
    )
    networks = [network for network, _, _ in taught]
    device = choose_device()
    encoder = HerdEncoder(networks, device, fingerprint)
    if record.exists() and json.loads(record.read_text())["fingerprint"] == fingerprint:
        for network, file, _ in taught:
            network.load_state_dict(load_file(str(file)))
            network.eval().requires_grad_(False)
            # The detector may be using the Apple GPU at this very moment.
            with mps_inference() if device == "mps" else nullcontext():
                network.to(device)
        vectors = np.load(described)
        logger.info("Herd model reloaded: %d cows", len(cows))
    else:
        samples = [
            (sample, index) for index, cow in enumerate(cows) for sample in cow.samples
        ]
        logger.info(
            "Learning the herd from %d confirmed photographs of %d cows on %s",
            len(samples),
            len(cows),
            device,
        )
        for seed, (network, _, start) in enumerate(taught):
            network.start(start)
            learn(
                store.read_image,
                samples,
                network,
                device,
                stopped,
                minimum_draws=minimum_draws,
                seed=seed,
            )
        batches = []
        for first in range(0, len(samples), 32):
            if stopped is not None and stopped.is_set():
                raise CancelledError("Herd learning stopped")
            batches.append(
                encoder.encode(
                    [
                        store.read_image(sample)
                        for sample, _ in samples[first : first + 32]
                    ]
                )
            )
        vectors = np.concatenate(batches)
        directory.mkdir(parents=True, exist_ok=True)
        # The record is written last: a model without its record is retaught.
        record.unlink(missing_ok=True)
        for network, file, _ in taught:
            save_file(network.state_dict(), str(file))
        np.save(described, vectors)
        record.write_text(json.dumps({"fingerprint": fingerprint}))
    return PreparedGallery(
        catalog,
        vectors,
        tuple((cow.id, cow.name) for cow in cows for _ in cow.samples),
        encoder,
        NEIGHBOURS,
        encoder.parts,
        SHARE,
    )
