"""Optional, single-camera Cutie ownership without identity or selection policy."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray

from aidetector.adapters.inference.device import mps_inference

if TYPE_CHECKING:
    from cutie.inference.inference_core import InferenceCore
    from cutie.model.cutie import CUTIE
    from omegaconf import DictConfig

SDK_VERSION = "1.0.0+aidetector.2"
WEIGHTS_SHA256 = "9c05402ee36d3a356fb72715d263ba7e1ea06ad3bada48c1306491792da43023"
MAX_OBJECTS = 8
# The SDK resizes indexed input through float32 before restoring int64. Keep
# every stable ID exactly representable; callers begin a fresh epoch at reset.
MAX_OBJECT_ID = 2**24


class CutieUnavailable(RuntimeError):
    """The explicitly selected experimental runtime is not installed correctly."""


@dataclass(frozen=True)
class MaskEvidence:
    object_id: int
    area: int
    mean_probability: float | None
    p10_probability: float | None


@dataclass(frozen=True)
class CutieOutput:
    """Source-sized stable IDs and model mask quality, never cow confidence."""

    mask: NDArray[np.int64]
    objects: tuple[MaskEvidence, ...]


def mask_evidence(
    mask: NDArray[np.int64],
    probabilities: NDArray[np.float32],
    channels: dict[int, int],
) -> tuple[MaskEvidence, ...]:
    """Use the current SDK mapping after channel compaction or object addition."""
    if (
        probabilities.ndim != 3
        or probabilities.shape[1:] != mask.shape
        or len(set(channels.values())) != len(channels)
        or any(not 0 < channel < len(probabilities) for channel in channels.values())
        or not set(np.unique(mask)).issubset({0, *channels})
        or not np.isfinite(probabilities).all()
    ):
        raise ValueError("Cutie returned invalid mask/probability correspondence")
    result = []
    for object_id, channel in channels.items():
        assigned = probabilities[channel][mask == object_id]
        result.append(
            MaskEvidence(
                object_id,
                int(assigned.size),
                float(assigned.mean()) if assigned.size else None,
                float(np.quantile(assigned, 0.1)) if assigned.size else None,
            )
        )
    return tuple(result)


def require_cutie_runtime() -> None:
    """Check the optional source-install extra before downloading model assets."""
    try:
        installed = version("cutie")
    except PackageNotFoundError as error:
        raise CutieUnavailable(
            "Continuous identity is a source-install-only experiment requiring "
            f"Cutie {SDK_VERSION}. Install "
            "the identity-continuous extra with uv sync --extra default "
            "--extra identity-continuous from the detector directory."
        ) from error
    if installed != SDK_VERSION:
        raise CutieUnavailable(f"Continuous tracking requires Cutie {SDK_VERSION}")


def _load_model(weights: Path) -> tuple[CUTIE, DictConfig]:
    # The full pinned checkpoint supplies every tensor. Disable ImageNet
    # initialization through the packaged SDK flag, without monkeypatches.
    try:
        import torch
        from cutie.model.cutie import CUTIE
        from hydra import compose, initialize_config_dir
        from omegaconf import OmegaConf
    except ModuleNotFoundError as error:
        raise CutieUnavailable(
            f"The optional Cutie runtime is incomplete: missing {error.name}"
        ) from error

    with weights.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != WEIGHTS_SHA256:
            raise ValueError("Cutie weights failed the SHA-256 check")
    with (
        as_file(files("cutie") / "config") as directory,
        initialize_config_dir(version_base="1.3.2", config_dir=str(directory)),
    ):
        config = compose(config_name="eval_config")
    # Match the frozen same-camera experiments. The pinned SDK owns every other
    # eval default, including the bounded working and long-term memory settings.
    config.max_internal_size = 480
    config.mem_every = 5
    config.use_long_term = True
    OmegaConf.update(config, "model.pretrained_backbone", False, force_add=True)
    model = CUTIE(config).float().eval().requires_grad_(False)
    model.load_state_dict(
        torch.load(weights, map_location="cpu", weights_only=True), strict=True
    )
    return model, config


class CutieRuntime:
    """One worker owns one camera core; use open_cutie to acquire/release it.

    The caller supplies chronological, same-geometry frames and disjoint NEW
    object masks from those exact pixels. It owns epoch checks, unique stable
    IDs, frame cadence, retirement decisions and names. IDs are not channels.
    CPU and MPS FP32 are the supported experimental execution targets.
    """

    def __init__(self, model: CUTIE, config: DictConfig, device: Literal["cpu", "mps"]):
        from cutie.inference.inference_core import InferenceCore

        self.device = device
        self._scope = mps_inference if device == "mps" else nullcontext
        self._model: CUTIE | None = model
        self._config = config
        self._core: InferenceCore | None = InferenceCore(model, config)
        self._shape: tuple[int, int] | None = None

    def _opened(self) -> InferenceCore:
        if self._core is None:
            raise RuntimeError("Cutie runtime is closed")
        return self._core

    @property
    def object_ids(self) -> tuple[int, ...]:
        return tuple(self._opened().object_manager.all_obj_ids)

    def _validate_input(
        self,
        image: NDArray[np.uint8],
        mask: NDArray[np.int64] | None,
        object_ids: tuple[int, ...],
    ) -> None:
        if (
            image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or not image.shape[0]
            or not image.shape[1]
        ):
            raise ValueError("Cutie requires a nonempty source BGR uint8 image")
        if self._shape is not None and image.shape[:2] != self._shape:
            raise ValueError("Reset Cutie before changing source geometry")
        active = set(self.object_ids)
        incoming = set(object_ids)
        if (
            len(incoming) != len(object_ids)
            or any(type(i) is not int or not 0 < i <= MAX_OBJECT_ID for i in incoming)
            or active & incoming
        ):
            raise ValueError(
                f"Seed IDs must be distinct NEW integers from 1 to {MAX_OBJECT_ID}"
            )
        if len(active) + len(incoming) > MAX_OBJECTS:
            raise ValueError("Cutie supports at most eight active objects")
        if mask is None:
            if incoming:
                raise ValueError("New objects require their same-frame indexed mask")
        elif (
            not incoming
            or mask.dtype != np.int64
            or mask.shape != image.shape[:2]
            or set(np.unique(mask)) - {0} != incoming
        ):
            raise ValueError("Indexed mask must contain exactly the supplied new IDs")

    def step(
        self,
        image: NDArray[np.uint8],
        *,
        mask: NDArray[np.int64] | None = None,
        object_ids: tuple[int, ...] = (),
    ) -> CutieOutput:
        import torch

        core = self._opened()
        self._validate_input(image, mask, object_ids)
        self._shape = (image.shape[0], image.shape[1])
        if not self.object_ids and mask is None:
            background = np.zeros(self._shape, dtype=np.int64)
            background.setflags(write=False)
            return CutieOutput(background, ())
        with self._scope(), torch.inference_mode():
            tensor = torch.from_numpy(image[:, :, ::-1].copy()).permute(2, 0, 1)
            tensor = tensor.to(self.device).float() / 255
            seed = (
                torch.from_numpy(mask.copy()).to(self.device)
                if mask is not None
                else None
            )
            probabilities = core.step(
                tensor,
                seed,
                objects=list(object_ids) if mask is not None else None,
                idx_mask=True,
            )
            stable = core.output_prob_to_mask(probabilities).cpu().numpy().copy()
            channels = {
                i: core.object_manager.find_tmp_by_id(i) for i in self.object_ids
            }
            evidence = mask_evidence(stable, probabilities.cpu().numpy(), channels)
            stable.setflags(write=False)
            return CutieOutput(stable, evidence)

    def retire(self, object_ids: tuple[int, ...]) -> None:
        core = self._opened()
        if not object_ids:
            return
        if not set(object_ids).issubset(self.object_ids):
            raise ValueError("Cannot retire an unknown object")
        with self._scope():
            core.delete_objects(list(object_ids))
            if not core.object_manager.all_obj_ids:
                self._replace_core()

    def _replace_core(self) -> None:
        from cutie.inference.inference_core import InferenceCore

        if self._model is None:
            raise RuntimeError("Cutie runtime is closed")
        self._core = InferenceCore(self._model, self._config)
        self._shape = None

    def reset(self) -> None:
        self._opened()
        with self._scope():
            self._replace_core()

    def close(self) -> None:
        if self._core is not None:
            with self._scope():
                self._core = None
                self._model = None
                self._shape = None


@contextmanager
def open_cutie(weights: Path, device: Literal["cpu", "mps"]) -> Iterator[CutieRuntime]:
    """Strict local loading; no model download, CUDA fallback or SDK patching."""
    if device not in ("cpu", "mps"):
        raise ValueError("This experimental Cutie runtime supports CPU and MPS only")
    require_cutie_runtime()
    scope = mps_inference if device == "mps" else nullcontext
    model = None
    with scope():
        try:
            model, config = _load_model(weights)
            model.to(device)
            runtime = CutieRuntime(model, config, device)
        finally:
            # Release a partially loaded/placed model under the same GPU scope.
            model = None
    try:
        yield runtime
    finally:
        runtime.close()
