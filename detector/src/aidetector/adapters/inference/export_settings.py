"""The SDK conversion contract shared by cached and direct model exports."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from aidetector.adapters.inference.onnx import InferenceOptions
from aidetector.configuration import OnnxConfig, YoloConfig


def export_arguments(
    config: YoloConfig,
    onnx: OnnxConfig,
    batch: int,
    options: InferenceOptions,
    model_format: Literal["onnx", "engine"] = "onnx",
) -> dict[str, Any]:
    return {
        "format": model_format,
        "batch": batch,
        "dynamic": True,
        "quantize": 16 if options.half else None,
        "imgsz": config.imgsz,
        "simplify": True,
        "opset": onnx.opset,
        # The head without suppression, where a model has one: what its confidence
        # thresholds were chosen with. The SDK no longer picks it by itself.
        "nms": False,
    }


def content_key(identity: dict[str, Any], source: Path) -> str:
    """Name a prepared model after what produced it and the checkpoint's bytes."""
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode())
    with source.open("rb") as checkpoint:
        return hashlib.file_digest(checkpoint, lambda: digest).hexdigest()
