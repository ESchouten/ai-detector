"""Optional local-weight research controls; no downloads or remote model code."""

import hashlib
import json
from pathlib import Path

import numpy as np
import timm
import torch
from PIL import Image
from torchvision import transforms

CHECKPOINTS = {
    "miewid": "adff92b39678f37eb74861c6399a741639a8907ec2382738e903d6120727b348",
    "megadescriptor": "8ffde82d9d58066bf124d03b938b6e7bf2e278c8fd4201710bf78a3ceb6029ef",
}


class GeM(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.p = torch.nn.Parameter(torch.full((1,), 3.0))

    def forward(self, values):
        return (
            values.clamp(min=1e-6)
            .pow(self.p)
            .mean((-2, -1), keepdim=True)
            .pow(1 / self.p)
        )


class MiewIDNetwork(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = timm.create_model(
            "efficientnetv2_rw_m", pretrained=False, num_classes=0
        )
        self.backbone.global_pool = GeM()
        self.bn = torch.nn.BatchNorm1d(2152)
        self.final = torch.nn.Linear(
            2152, 10
        )  # Checkpoint compatibility, unused in inference.

    def forward(self, values):
        return self.bn(self.backbone(values).flatten(1))


class ComparisonEncoder:
    def __init__(self, name: str, weights: Path, device: str):
        with weights.open("rb") as stream:
            weight_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if weight_hash != CHECKPOINTS[name]:
            raise ValueError(f"{name}: checkpoint differs from the pinned comparison")
        self.device = torch.device(device)
        if name == "miewid":
            from safetensors.torch import load_file

            self.model = MiewIDNetwork()
            self.model.load_state_dict(load_file(str(weights)), strict=True)
            self.transform = transforms.Compose(
                [
                    transforms.Resize(
                        (440, 440), interpolation=transforms.InterpolationMode.BILINEAR
                    ),
                    transforms.ToTensor(),
                    transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
                ]
            )
            self.image_size = 440
        else:
            from timm.models.swin_transformer import checkpoint_filter_fn

            self.model = timm.create_model(
                "swin_small_patch4_window7_224", pretrained=False, num_classes=0
            )
            state = torch.load(weights, map_location="cpu", weights_only=True)
            self.model.load_state_dict(
                checkpoint_filter_fn(state, self.model), strict=True
            )
            self.transform = timm.data.create_transform(
                input_size=(3, 224, 224),
                interpolation="bicubic",
                crop_pct=0.9,
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
                is_training=False,
            )
            self.image_size = 224
        self.model.eval().requires_grad_(False).to(self.device)
        self.fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "model": name,
                    "weights": weight_hash,
                    "timm": timm.__version__,
                    "implementation": hashlib.sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                    "transform": str(self.transform),
                    "precision": "float32",
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def encode(self, images):
        tensors = torch.stack(
            [self.transform(Image.fromarray(image[:, :, ::-1])) for image in images]
        )
        with torch.inference_mode():
            vectors = self.model(tensors.to(self.device))
            vectors = torch.nn.functional.normalize(vectors, dim=1)
        return vectors.cpu().numpy().astype(np.float32)
