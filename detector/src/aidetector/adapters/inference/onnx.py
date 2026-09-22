"""Process-scoped inference setup and isolated third-party compatibility hooks."""

import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib import import_module, util
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aidetector.configuration import OnnxConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceOptions:
    half: bool = False
    rectangular: bool = True


@dataclass(frozen=True)
class ModelRequirements:
    """Model format and dimensions needed to prepare execution providers."""

    path: str
    image_size: int
    batch_size: int


@dataclass(frozen=True)
class ProviderSelection:
    names: tuple[str, ...]
    devices: tuple[Any, ...] = ()

    @property
    def inference_options(self) -> InferenceOptions:
        first = self.names[0]
        return InferenceOptions(
            half=first
            not in {
                "CPUExecutionProvider",
                "OpenVINOExecutionProvider",
                "AzureExecutionProvider",
            },
            rectangular=first != "NvTensorRTRTXExecutionProvider",
        )


def _set_environment(resources: ExitStack, name: str, value: str) -> None:
    previous = os.environ.get(name)

    def restore() -> None:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

    resources.callback(restore)
    os.environ[name] = value


def _cuda_libraries(resources: ExitStack) -> None:
    if sys.platform != "win32":
        return
    directories: set[Path] = set()
    for package in (
        "nvidia.cuda_nvrtc",
        "nvidia.cuda_runtime",
        "nvidia.cufft",
        "nvidia.curand",
        "nvidia.cudnn",
        "tensorrt",
        "tensorrt_bindings",
        "tensorrt_libs",
        "tensorrt_cu12_bindings",
        "tensorrt_cu12_libs",
    ):
        try:
            spec = util.find_spec(package)
        except ModuleNotFoundError:
            continue
        if spec is None or spec.submodule_search_locations is None:
            continue
        for location in spec.submodule_search_locations:
            root = Path(location)
            directories.update(path.parent for path in root.glob("**/*.dll"))
    for directory in sorted(directories):
        resources.enter_context(os.add_dll_directory(str(directory)))
    if directories:
        _set_environment(
            resources,
            "PATH",
            os.pathsep.join(
                [
                    *(str(path) for path in sorted(directories)),
                    os.environ.get("PATH", ""),
                ]
            ),
        )


def _register_windows_ml(resources: ExitStack, ort: Any) -> set[str]:
    # Optional, Windows-only SDKs are imported only for this distribution. The
    # executable build explicitly collects these modules.
    winml = import_module("winui3.microsoft.windows.ai.machinelearning")
    bootstrap = import_module(
        "winui3.microsoft.windows.applicationmodel.dynamicdependency.bootstrap"
    )
    resources.enter_context(
        bootstrap.initialize(options=bootstrap.InitializeOptions.ON_NO_MATCH_SHOW_UI)
    )
    registered: set[str] = set()
    for provider in winml.ExecutionProviderCatalog.get_default().find_all_providers():
        provider.ensure_ready_async().get()
        if provider.library_path:
            ort.register_execution_provider_library(
                provider.name, provider.library_path
            )
            resources.callback(ort.unregister_execution_provider_library, provider.name)
            registered.add(provider.name)
    logger.info("Registered Windows ML providers: %s", sorted(registered))
    return registered


def select_devices(devices: list[Any]) -> list[Any]:
    """Use one device per provider, preferring its GPU over its CPU."""
    selected: dict[str, Any] = {}
    for device in devices:
        if device.ep_name not in selected or str(device.device.type).endswith("GPU"):
            selected[device.ep_name] = device
    names = sorted(
        selected, key=lambda name: (name == "OpenVINOExecutionProvider", name)
    )
    return [selected[name] for name in names]


def select_providers(
    available: list[str], devices: list[Any], requested: str | None
) -> ProviderSelection:
    """Choose from installed providers and registered Windows ML devices."""
    if requested is not None:
        devices = [device for device in devices if device.ep_name == requested]
        if requested not in available and not devices:
            raise ValueError(f"Configured ONNX provider is unavailable: {requested}")
        available = [requested]
    selected = tuple(select_devices(devices))
    names = tuple(device.ep_name for device in selected) or tuple(available)
    return ProviderSelection(names, selected)


def tensorrt_profiles(models: tuple[ModelRequirements, ...]) -> dict[str, str]:
    if not models:
        return {}
    sizes = [model.image_size for model in models]
    batch = max(model.batch_size for model in models)
    return {
        "nv_profile_min_shapes": f"images:1x3x{min(sizes)}x{min(sizes)}",
        "nv_profile_opt_shapes": f"images:{batch}x3x{max(sizes)}x{max(sizes)}",
        "nv_profile_max_shapes": f"images:{batch}x3x{max(sizes)}x{max(sizes)}",
    }


def _is_onnx_model(model: str) -> bool:
    url = urlsplit(model)
    path = url.path if url.scheme in {"http", "https"} else model
    return path.endswith(".onnx")


@contextmanager
def inference_runtime(
    config: OnnxConfig,
    models: tuple[ModelRequirements, ...],
    build_type: str,
) -> Iterator[InferenceOptions]:
    """Keep provider libraries, session hooks and environment in one cleanup scope."""
    with ExitStack() as resources:
        # Installed dependencies belong to the distribution, never to an
        # inference library's opportunistic pip-install path.
        _set_environment(resources, "ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS", "1")
        _set_environment(resources, "YOLO_AUTOINSTALL", "false")
        uses_cuda = build_type in ("cuda", "tensorrt")
        if uses_cuda:
            _cuda_libraries(resources)
        if not models:
            yield InferenceOptions()
            return
        if uses_cuda and all(not _is_onnx_model(model.path) for model in models):
            yield InferenceOptions(half=True)
            return

        import onnxruntime as ort

        if uses_cuda:
            ort.preload_dlls(directory="")

        providers = _providers(config, build_type, resources, ort)
        _install_sessions(tensorrt_profiles(models), resources, ort, providers)
        logger.info("ONNX execution providers: %s", providers.names)
        yield providers.inference_options


def _providers(
    config: OnnxConfig, build_type: str, resources: ExitStack, ort: Any
) -> ProviderSelection:
    registered: set[str] = set()
    in_ci = any(
        os.environ.get(name, "").lower() in {"1", "true", "yes"}
        for name in ("CI", "GITHUB_ACTIONS")
    )
    if build_type == "windowsml" and config.winml and not in_ci:
        registered = _register_windows_ml(resources, ort)
    devices = [
        device for device in ort.get_ep_devices() if device.ep_name in registered
    ]
    return select_providers(ort.get_available_providers(), devices, config.provider)


def _install_sessions(
    profiles: dict[str, str],
    resources: ExitStack,
    ort: Any,
    selection: ProviderSelection,
) -> None:
    original_session = ort.InferenceSession
    scratch = Path(
        resources.enter_context(tempfile.TemporaryDirectory(prefix="aidetector-ort-"))
    )

    def session(path_or_bytes, sess_options=None, providers=None, **kwargs):
        options = sess_options if sess_options is not None else ort.SessionOptions()
        if selection.devices:
            for device in selection.devices:
                options.add_provider_for_devices(
                    [device], _device_options(profiles, device, scratch)
                )
            return original_session(path_or_bytes, sess_options=options, **kwargs)
        return original_session(
            path_or_bytes,
            sess_options=options,
            providers=[(name, _provider_options(name)) for name in selection.names],
            **kwargs,
        )

    resources.callback(setattr, ort, "InferenceSession", original_session)
    ort.InferenceSession = session


def _device_options(
    profiles: dict[str, str], device: Any, scratch: Path
) -> dict[str, str]:
    if device.ep_name == "NvTensorRTRTXExecutionProvider":
        return profiles
    if device.ep_name == "OpenVINOExecutionProvider":
        kind = "GPU" if str(device.device.type).endswith("GPU") else "CPU"
        path = scratch / f"openvino-{kind.lower()}.json"
        path.write_text(
            json.dumps({kind: {"INFERENCE_PRECISION_HINT": "f32"}}),
            encoding="utf-8",
        )
        return {"load_config": str(path)}
    return {}


def _provider_options(name: str) -> dict[str, str]:
    if name == "CoreMLExecutionProvider":
        return {
            "ModelFormat": "MLProgram",
            "SpecializationStrategy": "FastPrediction",
            "EnableOnSubgraphs": "1",
            "AllowLowPrecisionAccumulationOnGPU": "1",
        }
    return {}
