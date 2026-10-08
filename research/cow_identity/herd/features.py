"""Frozen image descriptors for the herd-learning study, cached by image content.

Every backbone is used as published: no fine-tuning happens here. A cache file
belongs to one encoder contract (weights, preprocessing, precision), so changing
any of them produces a different file instead of silently mixing vectors.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "detector" / "src"))

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
PAD_COLOR = (124, 116, 104)

# name: (kind, source, revision, input size)
ENCODERS = {
    "miewid": ("miewid", "conservationxlabs/miewid-msv3", None, 440),
    "dinov2-s-224": ("dino", "facebook/dinov2-small", None, 224),
    "dinov2-b-224": ("dino", "facebook/dinov2-base", None, 224),
    "dinov2-b-448": ("dino", "facebook/dinov2-base", None, 448),
    "dinov2-l-224": ("dino", "facebook/dinov2-large", None, 224),
    "dinov2-l-448": ("dino", "facebook/dinov2-large", None, 448),
    "megadescriptor-l-384": ("timm", "hf-hub:BVRA/MegaDescriptor-L-384", None, 384),
}


def letterbox(image, size):
    """Keep the whole animal and its proportions; pad the shorter side."""
    height, width = image.shape[:2]
    scale = size / max(height, width)
    resized = cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    canvas = np.full((size, size, 3), PAD_COLOR[::-1], dtype=np.uint8)
    top = (size - resized.shape[0]) // 2
    left = (size - resized.shape[1]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    return canvas


def to_tensor(images):
    pixels = np.stack(images)[:, :, :, ::-1].astype(np.float32) / 255.0
    pixels = (pixels - IMAGENET_MEAN) / IMAGENET_STD
    return torch.from_numpy(pixels.transpose(0, 3, 1, 2).astype(np.float32))


def prepare(image, kind, size):
    if kind == "dino":
        return letterbox(image, size)
    return cv2.resize(image, (size, size), interpolation=cv2.INTER_LINEAR)


class Encoder:
    """One frozen backbone. `encode` takes BGR crops and returns L2-normalised rows."""

    def __init__(self, name, device="mps"):
        kind, source, revision, size = ENCODERS[name]
        self.name, self.kind, self.size, self.device = name, kind, size, device
        if kind == "miewid":
            from huggingface_hub import hf_hub_download

            from aidetector.adapters.inference.miewid import (
                REVISION,
                WEIGHTS_SHA256,
                MiewidNetwork,
            )
            from safetensors.torch import load_file

            weights = hf_hub_download(source, "model.safetensors", revision=REVISION)
            self.model = MiewidNetwork()
            self.model.load_state_dict(load_file(weights), strict=True)
            identity = WEIGHTS_SHA256
            preprocessing = "bgr-stretch-bilinear-imagenet-gem-bn"
        elif kind == "dino":
            from transformers import AutoModel

            self.model = AutoModel.from_pretrained(source, revision=revision)
            identity = f"{source}@{self.model.config._commit_hash}"
            preprocessing = "bgr-letterbox-imagenet-cls+meanpatch"
        else:
            import timm

            self.model = timm.create_model(source, pretrained=True, num_classes=0)
            identity = source
            preprocessing = "bgr-stretch-bilinear-imagenet-pooled"
        self.model.eval().requires_grad_(False).to(device)
        contract = {
            "identity": identity,
            "preprocessing": preprocessing,
            "size": size,
            "precision": "float32",
            "torch": torch.__version__,
        }
        self.contract = contract
        self.fingerprint = hashlib.sha256(
            json.dumps(contract, sort_keys=True).encode()
        ).hexdigest()[:16]

    def prepare(self, image):
        return prepare(image, self.kind, self.size)

    @torch.inference_mode()
    def encode_prepared(self, images):
        tensor = to_tensor(images).to(self.device)
        if self.kind == "dino":
            tokens = self.model(pixel_values=tensor).last_hidden_state
            registers = getattr(self.model.config, "num_register_tokens", 0)
            vectors = torch.cat(
                [
                    torch.nn.functional.normalize(tokens[:, 0], dim=1),
                    torch.nn.functional.normalize(
                        tokens[:, 1 + registers :].mean(1), dim=1
                    ),
                ],
                dim=1,
            )
        else:
            vectors = self.model(tensor)
        vectors = torch.nn.functional.normalize(vectors.float(), dim=1)
        return vectors.cpu().numpy()

    def encode(self, images):
        return self.encode_prepared([self.prepare(image) for image in images])


class _Files(torch.utils.data.Dataset):
    def __init__(self, paths, kind, size):
        self.paths, self.kind, self.size = paths, kind, size

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, index):
        data = Path(self.paths[index]).read_bytes()
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Unreadable image: {self.paths[index]}")
        return hashlib.sha256(data).hexdigest(), prepare(image, self.kind, self.size)


def _collate(rows):
    return [row[0] for row in rows], [row[1] for row in rows]


def encode_files(paths, name, cache_directory, device="mps", batch=16, workers=6):
    """Return (digests, vectors) for image files, encoding only uncached content."""
    cache_directory = Path(cache_directory)
    cache_directory.mkdir(parents=True, exist_ok=True)
    encoder = Encoder(name, device)
    store = cache_directory / f"{name}-{encoder.fingerprint}.npz"
    known = {}
    if store.exists():
        saved = np.load(store, allow_pickle=False)
        known = dict(zip(saved["digest"].tolist(), saved["vector"], strict=True))
    digests = [None] * len(paths)
    pending = []
    loader = torch.utils.data.DataLoader(
        _Files(paths, encoder.kind, encoder.size),
        batch_size=batch,
        num_workers=workers,
        collate_fn=_collate,
    )
    started = time.perf_counter()
    encoded = 0
    for step, (keys, images) in enumerate(loader):
        for offset, key in enumerate(keys):
            digests[step * batch + offset] = key
        fresh = [i for i, key in enumerate(keys) if key not in known]
        if fresh:
            vectors = encoder.encode_prepared([images[i] for i in fresh])
            for i, vector in zip(fresh, vectors, strict=True):
                known[keys[i]] = vector
            encoded += len(fresh)
            pending.append(len(fresh))
        if step % 50 == 0:
            print(
                f"{name}: {min((step + 1) * batch, len(paths))}/{len(paths)} "
                f"({encoded} new, {time.perf_counter() - started:.0f}s)",
                flush=True,
            )
    if pending:
        np.savez(
            store,
            digest=np.array(list(known)),
            vector=np.stack(list(known.values())).astype(np.float32),
        )
        (cache_directory / f"{name}-{encoder.fingerprint}.json").write_text(
            json.dumps(encoder.contract, indent=2) + "\n"
        )
    return digests, np.stack([known[key] for key in digests]), encoder.contract


def cached_vectors(paths, name, cache_directory):
    """Vectors already computed for these files, without loading the backbone."""
    cache_directory = Path(cache_directory)
    stores = sorted(cache_directory.glob(f"{name}-*.npz"))
    if len(stores) != 1:
        raise FileNotFoundError(f"Expected one cache for {name}, found {len(stores)}")
    saved = np.load(stores[0], allow_pickle=False)
    known = dict(zip(saved["digest"].tolist(), saved["vector"], strict=True))
    index = cache_directory / "digests.json"
    digests = json.loads(index.read_text()) if index.exists() else {}
    fresh = False
    keys = []
    for path in paths:
        stat = Path(path).stat()
        key = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
        if key not in digests:
            digests[key] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            fresh = True
        keys.append(digests[key])
    if fresh:
        index.write_text(json.dumps(digests))
    return np.stack([known[key] for key in keys])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON list of rows with a path")
    parser.add_argument("--encoder", required=True, choices=sorted(ENCODERS))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--batch", type=int, default=16)
    arguments = parser.parse_args()
    rows = json.loads(arguments.manifest.read_text())
    root = arguments.manifest.parent
    started = time.perf_counter()
    digests, vectors, _ = encode_files(
        [str(root / row["path"]) for row in rows],
        arguments.encoder,
        arguments.cache,
        arguments.device,
        arguments.batch,
    )
    print(
        f"{arguments.encoder}: {vectors.shape} in {time.perf_counter() - started:.1f}s"
    )


if __name__ == "__main__":
    main()
