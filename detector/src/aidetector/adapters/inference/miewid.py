"""Reviewed MIEWid msv3 architecture for the non-commercial identity trial."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from contextlib import nullcontext
from importlib.metadata import version
from pathlib import Path
from threading import Lock

import numpy as np
import torch
from numpy.typing import NDArray

from aidetector.adapters.inference.device import mps_inference
from aidetector.adapters.inference.identity import download_identity_asset

logger = logging.getLogger(__name__)
MODEL = "conservationxlabs/miewid-msv3"
REVISION = "4f1d7f2b521149e5fe34bb85f377248ce9971a7d"
WEIGHTS_SHA256 = "adff92b39678f37eb74861c6399a741639a8907ec2382738e903d6120727b348"


class GeM(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.p = torch.nn.Parameter(torch.full((1,), 3.0))

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return (
            values.clamp(min=1e-6)
            .pow(self.p)
            .mean((-2, -1), keepdim=True)
            .pow(1 / self.p)
        )


class MiewidNetwork(torch.nn.Module):
    def __init__(self):
        super().__init__()
        import timm

        self.backbone = timm.create_model(
            "efficientnetv2_rw_m", pretrained=False, num_classes=0
        )
        self.backbone.global_pool = GeM()
        self.bn = torch.nn.BatchNorm1d(2152)
        # Retain the publisher's classifier for strict checkpoint compatibility.
        self.final = torch.nn.Linear(2152, 10)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.bn(self.backbone(values).flatten(1))


class MiewidEncoder:
    dimension = 2152

    def __init__(
        self, cache_directory: Path, device: str = "auto", weights: Path | None = None
    ):
        from safetensors.torch import load_file
        from torchvision import transforms

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cpu" and torch.backends.mps.is_available():
                device = "mps"
        self.device = device
        self._lock = Lock()
        weights = weights or download_identity_asset(
            MODEL,
            "model.safetensors",
            REVISION,
            cache_directory,
        )
        with weights.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != WEIGHTS_SHA256:
                raise OSError("Identity weights failed the SHA-256 check")
        self.model = MiewidNetwork()
        self.model.load_state_dict(load_file(str(weights)), strict=True)
        self.model.eval().requires_grad_(False)
        scope = mps_inference if device == "mps" else nullcontext
        with scope():
            self.model.to(device)
        self.transform = transforms.Compose(
            [
                transforms.Resize(
                    (440, 440), interpolation=transforms.InterpolationMode.BILINEAR
                ),
                transforms.ToTensor(),
                transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
            ]
        )
        contract = {
            "weights": WEIGHTS_SHA256,
            "preprocessing": "rgb-bilinear-stretch440-imagenet-gem-bn-l2-v1",
            "device": device,
            "precision": "float32",
            "libraries": {
                name: version(name)
                for name in ("torch", "torchvision", "timm", "Pillow")
            },
        }
        self.fingerprint = hashlib.sha256(
            json.dumps(contract, sort_keys=True).encode()
        ).hexdigest()
        logger.info(
            "Identity encoder ready: MIEWid msv3; %s FP32; confirmed-gallery suggestions",
            device,
        )

    def encode(self, images: Sequence[NDArray[np.uint8]]) -> NDArray[np.float32]:
        from PIL import Image

        if not images:
            return np.empty((0, self.dimension), dtype=np.float32)
        pixels = torch.stack(
            [self.transform(Image.fromarray(image[:, :, ::-1])) for image in images]
        )
        scope = mps_inference if self.device == "mps" else nullcontext
        with self._lock, scope(), torch.inference_mode():
            vectors = torch.nn.functional.normalize(
                self.model(pixels.to(self.device)), dim=1
            )
            return vectors.cpu().numpy().copy()
