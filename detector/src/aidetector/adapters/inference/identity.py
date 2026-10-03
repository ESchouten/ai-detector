"""Pinned image descriptors and a content-addressed cache for visual identity."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Sequence
from contextlib import nullcontext
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.inference.device import mps_inference

logger = logging.getLogger(__name__)
MODEL = "facebook/dinov2-small"
REVISION = "ed25f3a31f01632728cabb09d1542f84ab7b0056"
WEIGHTS_SHA256 = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"


class ImageEncoder(Protocol):
    fingerprint: str
    dimension: int

    def encode(self, images: Sequence[NDArray[np.uint8]]) -> NDArray[np.float32]: ...


class DinoEncoder:
    """Keep the complete cow crop; no remote model code or hidden augmentation."""

    dimension = 384

    def __init__(
        self, cache_directory: Path, device: str = "auto", image_size: int = 224
    ):
        import torch
        from huggingface_hub import hf_hub_download
        from transformers.models.dinov2.modeling_dinov2 import Dinov2Model

        if image_size not in (224, 336):
            raise ValueError("Identity image size must be 224 or 336")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cpu" and torch.backends.mps.is_available():
                device = "mps"
        self.device = device
        self.image_size = image_size
        self._lock = Lock()
        logger.info("Opening identity encoder %s on %s (FP32)", MODEL, device)
        files = {
            name: Path(
                hf_hub_download(
                    MODEL,
                    name,
                    revision=REVISION,
                    cache_dir=cache_directory,
                    token=False,
                )
            )
            for name in ("config.json", "model.safetensors")
        }
        with files["model.safetensors"].open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != WEIGHTS_SHA256:
                raise ValueError("Downloaded identity weights failed the SHA-256 check")
        self.model = (
            Dinov2Model.from_pretrained(
                files["config.json"].parent,
                local_files_only=True,
                use_safetensors=True,
                attn_implementation="sdpa",
            )
            .eval()
            .to(device)
        )
        contract = {
            "weights": WEIGHTS_SHA256,
            "preprocessing": "rgb-pil-bicubic-pad-imagenet-cls-l2-v1",
            "size": image_size,
            "device": device,
            "precision": "float32",
            "libraries": {
                name: version(name) for name in ("torch", "transformers", "Pillow")
            },
        }
        self.fingerprint = hashlib.sha256(
            json.dumps(contract, sort_keys=True).encode()
        ).hexdigest()

    def encode(self, images: Sequence[NDArray[np.uint8]]) -> NDArray[np.float32]:
        import torch
        from PIL import Image, ImageOps

        if not images:
            return np.empty((0, 384), dtype=np.float32)
        pixels = np.stack(
            [
                np.asarray(
                    ImageOps.pad(
                        Image.fromarray(image[:, :, ::-1]),
                        (self.image_size, self.image_size),
                        method=Image.Resampling.BICUBIC,
                        color=(124, 116, 104),
                    ),
                    dtype=np.float32,
                )
                for image in images
            ]
        )
        pixels = (pixels / 255.0 - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
        tensor = torch.from_numpy(pixels.transpose(0, 3, 1, 2).astype(np.float32))
        scope = mps_inference if self.device == "mps" else nullcontext
        with self._lock, scope(), torch.inference_mode():
            output = self.model(pixel_values=tensor.to(self.device)).last_hidden_state
            vectors = torch.nn.functional.normalize(output[:, 0, :], dim=1)
            return vectors.cpu().numpy().copy()


class EmbeddingCache:
    """SQLite owns publication; keys include actual pixels and encoder provenance."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS embeddings "
            "(key TEXT PRIMARY KEY, vector BLOB NOT NULL)"
        )

    def close(self) -> None:
        self._connection.close()

    def encode(
        self, encoder: ImageEncoder, images: Sequence[NDArray[np.uint8]]
    ) -> NDArray[np.float32]:
        if not images:
            return np.empty((0, encoder.dimension), dtype=np.float32)
        keys = [self.key(encoder.fingerprint, image) for image in images]
        with self._lock:
            vectors = {
                key: np.frombuffer(row[0], dtype=np.float32).copy()
                for key in dict.fromkeys(keys)
                if (
                    row := self._connection.execute(
                        "SELECT vector FROM embeddings WHERE key = ?", (key,)
                    ).fetchone()
                )
            }
            missing = {
                key: image
                for key, image in zip(keys, images, strict=True)
                if key not in vectors
            }
            for start in range(0, len(missing), 8):
                chunk = list(missing.items())[start : start + 8]
                encoded = encoder.encode([image for _, image in chunk])
                if (
                    encoded.shape != (len(chunk), encoder.dimension)
                    or not np.isfinite(encoded).all()
                ):
                    raise ValueError("Identity encoder returned invalid embeddings")
                with self._connection:
                    for (key, _), vector in zip(chunk, encoded, strict=True):
                        self._connection.execute(
                            "INSERT OR REPLACE INTO embeddings VALUES (?, ?)",
                            (key, vector.astype(np.float32).tobytes()),
                        )
                        vectors[key] = vector
        result = np.stack([vectors[key] for key in keys])
        if (
            result.shape != (len(images), encoder.dimension)
            or not np.isfinite(result).all()
        ):
            raise ValueError("Identity embedding cache contains invalid vectors")
        return result

    @staticmethod
    def key(fingerprint: str, image: NDArray[np.uint8]) -> str:
        digest = hashlib.sha256(fingerprint.encode())
        digest.update(str(image.shape).encode())
        digest.update(str(image.dtype).encode())
        digest.update(image.tobytes())
        return digest.hexdigest()
