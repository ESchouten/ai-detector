"""The SDK conversion contract shared by cached and direct model exports."""

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
    }
