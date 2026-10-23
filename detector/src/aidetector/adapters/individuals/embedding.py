"""Run a bring-your-own ONNX embedding model on pictures of individuals.

The model takes float32 RGB pictures as N×3×H×W, with a fixed height and
width, and returns one embedding per picture as N×D. Its metadata may set
`mean` and `std`, three comma-separated values each on the 0 to 1 scale, for
the normalisation it was trained with; ImageNet's are used otherwise.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def input_size(path: str) -> int:
    """The larger side of the model's input, for preparing execution providers."""
    import onnx

    model = onnx.load(path, load_external_data=False)
    dimensions = model.graph.input[0].type.tensor_type.shape.dim
    sizes = [dimension.dim_value for dimension in dimensions[2:]]
    if len(dimensions) != 4 or not all(sizes):
        raise ValueError(
            "The individuals model needs an N×3×H×W input with a fixed height and width"
        )
    return max(sizes)


def model_key(path: str) -> str:
    """Name embeddings by the model file that made them."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        while chunk := file.read(2**20):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _triple(metadata: dict[str, str], key: str, default: tuple[float, ...]):
    if key not in metadata:
        return np.asarray(default, np.float32)
    values = [float(value) for value in metadata[key].split(",")]
    if len(values) != 3:
        raise ValueError(f"The individuals model's {key} needs three values")
    return np.asarray(values, np.float32)


class EmbeddingModel:
    """One ONNX Runtime session, shared by the delivery workers.

    Create it inside the inference runtime's scope, which supplies execution
    providers. ONNX Runtime allows concurrent runs on one session.
    """

    def __init__(self, path: str, key: str):
        import onnxruntime as ort

        self.key = key
        self._session: Any = ort.InferenceSession(path)
        self.providers: tuple[str, ...] = tuple(self._session.get_providers())
        model_input = self._session.get_inputs()[0]
        self._input = model_input.name
        batch, _, height, width = model_input.shape
        self._size = (int(width), int(height))
        # A fixed batch of one takes its pictures one at a time.
        self._batch = 1 if batch == 1 else None
        metadata = self._session.get_modelmeta().custom_metadata_map
        self._mean = _triple(metadata, "mean", IMAGENET_MEAN)
        self._std = _triple(metadata, "std", IMAGENET_STD)

    def _pixels(self, image: NDArray[np.uint8]) -> NDArray[np.float32]:
        height, width = image.shape[:2]
        shrinking = width > self._size[0] or height > self._size[1]
        resized = cv2.resize(
            image,
            self._size,
            interpolation=cv2.INTER_AREA if shrinking else cv2.INTER_CUBIC,
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        return ((rgb - self._mean) / self._std).transpose(2, 0, 1)

    def embed(self, images: Sequence[NDArray[np.uint8]]) -> NDArray[np.float32]:
        """L2-normalised embeddings of BGR pictures, one row each."""
        pixels = np.stack([self._pixels(image) for image in images])
        size = self._batch or len(pixels)
        vectors = np.concatenate(
            [
                self._session.run(None, {self._input: pixels[start : start + size]})[0]
                for start in range(0, len(pixels), size)
            ]
        ).astype(np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
