"""Pinned MegaDescriptor-B controls for both publisher preprocessing recipes."""

import hashlib
import json
from importlib.metadata import version

import timm
import torch
from benchmark import digest
from comparison_encoders import ComparisonEncoder
from torchvision import transforms

MODEL = "BVRA/MegaDescriptor-B-224"
REVISION = "94bad65ce10660d59581d99378e5b6f16524c02a"
WEIGHTS_SHA256 = "655791158167f07773a890368f7db2fced85d569b9bccbbe7e5194e5051e2459"


class MegaBEncoder(ComparisonEncoder):
    dimension = 1024

    def __init__(self, weights, device="mps", preprocessing="config"):
        from timm.models.swin_transformer import checkpoint_filter_fn

        if digest(weights) != WEIGHTS_SHA256:
            raise ValueError(
                "MegaDescriptor-B checkpoint differs from the pinned upstream file"
            )
        self.device = torch.device(device)
        self.model = timm.create_model(
            "swin_base_patch4_window7_224", pretrained=False, num_classes=0
        )
        state = torch.load(weights, map_location="cpu", weights_only=True)
        self.model.load_state_dict(checkpoint_filter_fn(state, self.model), strict=True)
        self.model.eval().requires_grad_(False).to(self.device)
        if preprocessing == "notebook":
            self.transform = transforms.Compose(
                [
                    transforms.Resize((224, 224)),
                    transforms.ToTensor(),
                    transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
                ]
            )
            preprocess = "Published inference notebook:224bilinear,full-crop-stretch,ImageNet-normalization,v1"
        else:
            self.transform = timm.data.create_transform(
                input_size=(3, 224, 224),
                interpolation="bicubic",
                crop_pct=0.9,
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
                is_training=False,
            )
            preprocess = "Published config.json:224bicubic,center-crop0.9,ImageNet-normalization,v1"
        self.fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "model": MODEL,
                    "revision": REVISION,
                    "weights": WEIGHTS_SHA256,
                    "preprocess": preprocess,
                    "device": device,
                    "precision": "float32",
                    "libraries": {
                        name: version(name)
                        for name in ("torch", "torchvision", "timm", "Pillow")
                    },
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
