"""Check native provider startup outside the long-lived inference process."""

import faulthandler
import logging
import subprocess
import sys
from io import TextIOWrapper
from typing import cast

logger = logging.getLogger(__name__)
PROBE_TIMEOUT = 30.0


def probe_provider(provider: str) -> bool:
    """A listed provider may still crash natively while creating its first session."""
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.extend(["-m", "aidetector"])
    command.extend(["--probe-onnx-provider", provider])
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("ONNX provider %s startup probe failed: %s", provider, error)
        return False
    if result.stderr:
        logger.info(
            "ONNX provider %s probe diagnostics:\n%s", provider, result.stderr.rstrip()
        )
    if result.returncode:
        logger.warning(
            "ONNX provider %s startup probe exited with status %s",
            provider,
            result.returncode,
        )
        return False
    return True


def run_probe(provider: str) -> int:
    """Internal CLI action: exercise session creation and inference without PyWinRT."""
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    cast(TextIOWrapper, sys.stderr).reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    faulthandler.enable()
    import numpy as np
    import onnxruntime as ort
    from onnx import TensorProto, helper

    try:
        devices = [
            device for device in ort.get_ep_devices() if device.ep_name == provider
        ]
        device = next(
            (
                device
                for device in reversed(devices)
                if str(device.device.type).endswith("GPU")
            ),
            devices[0] if devices else None,
        )
        if provider not in ort.get_available_providers() and device is None:
            raise ValueError(f"Configured ONNX provider is unavailable: {provider}")
        logger.info("Probing ONNX provider %s session creation", provider)
        options = ort.SessionOptions()
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        if provider != "CPUExecutionProvider":
            options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
        if device is not None:
            options.add_provider_for_devices([device], {})
        graph = helper.make_graph(
            [helper.make_node("MatMul", ["x", "x"], ["y"])],
            "provider-startup",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [2, 2])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [2, 2])],
        )
        model = helper.make_model(
            graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=9
        )
        session = ort.InferenceSession(
            model.SerializeToString(),
            sess_options=options,
            providers=None if device is not None else [provider],
        )
        session.disable_fallback()
        if provider not in session.get_providers():
            raise RuntimeError(f"Provider was not activated: {provider}")
        inputs = np.array([[1, 2], [3, 4]], dtype=np.float32)
        output = cast(np.ndarray, session.run(None, {"x": inputs})[0])
        if not np.allclose(output, inputs @ inputs):
            raise RuntimeError("Provider returned an incorrect inference result")
    except Exception:
        # This child supervises native startup; its caller retains the diagnostics.
        logger.exception("ONNX provider %s startup probe failed", provider)
        return 1
    logger.info("ONNX provider %s startup probe passed", provider)
    return 0
