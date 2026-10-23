"""Count matching coat details between two pictures: ALIKED keypoints, LightGlue.

The embedding says which cows look alike overall; matched keypoints say whether
the same patches of coat show in both pictures. WildFusion (Cermak et al., 2024)
combines the two and gains 8.5 points of top-1 over MegaDescriptor alone on 17
animal datasets. Both networks are freely licensed (BSD and Apache 2.0) and run
through kornia.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image


class Matcher(Protocol):
    name: str

    def matches(self, pairs: Sequence[tuple[Path, Path]]) -> NDArray[np.float32]:
        """Confident keypoint matches for each pair of pictures."""
        ...


class KeypointMatcher:
    """ALIKED keypoints on pictures scaled to `size` px, matched by LightGlue.

    A pair's count is the number of matches LightGlue is at least `confidence`
    sure of. Keypoints are kept in memory and pair counts in `cache`, so a second
    run only matches new pairs.
    """

    def __init__(
        self,
        size: int = 512,
        keypoints: int = 512,
        confidence: float = 0.5,
        grayscale: bool = False,
        batch_size: int = 16,
        device: str | None = None,
        cache: Path | None = None,
    ) -> None:
        import kornia.feature as features
        import torch

        from reid.backbones import default_device

        self.device = torch.device(device or default_device())
        self.size = size
        self.confidence = confidence
        self.grayscale = grayscale
        self.batch_size = batch_size
        self.extractor = features.ALIKED.from_pretrained(
            "aliked-n16", max_num_keypoints=keypoints, device=self.device
        )
        # Early stopping and point pruning work one pair at a time; without
        # them pairs can be matched in batches.
        self.glue = (
            features.LightGlue("aliked", depth_confidence=-1, width_confidence=-1)
            .to(self.device)
            .eval()
        )
        self.name = f"aliked-lightglue-{size}px-{keypoints}" + (
            "+gray" if grayscale else ""
        )
        self._described: dict[Path, tuple[Any, Any, Any]] = {}
        self._cache = cache / f"{self.name}-c{confidence}.json" if cache else None
        self._counts: dict[str, float] = {}
        if self._cache is not None and self._cache.exists():
            self._counts = json.loads(self._cache.read_text(encoding="utf-8"))

    def _describe(self, path: Path) -> tuple[Any, Any, Any]:
        import torch

        if path not in self._described:
            with Image.open(path) as picture:
                picture = picture.convert("L" if self.grayscale else "RGB")
                picture = picture.convert("RGB")
                scale = self.size / max(picture.size)
                picture = picture.resize(
                    (
                        max(32, round(picture.width * scale)),
                        max(32, round(picture.height * scale)),
                    ),
                    Image.Resampling.BILINEAR,
                )
            pixels = np.asarray(picture, dtype=np.float32) / 255.0
            image = torch.from_numpy(pixels).permute(2, 0, 1)[None].to(self.device)
            with torch.inference_mode():
                found = self.extractor(image)[0]
            size = torch.tensor(
                [image.shape[-1], image.shape[-2]],
                device=self.device,
                dtype=torch.float32,
            )
            self._described[path] = (found.keypoints, found.descriptors, size)
        return self._described[path]

    def matches(self, pairs: Sequence[tuple[Path, Path]]) -> NDArray[np.float32]:
        import torch

        keys = [f"{a}\t{b}" for a, b in pairs]
        todo: dict[int, list[int]] = {}
        for position, key in enumerate(keys):
            if key not in self._counts:
                count = len(self._describe(pairs[position][0])[0])
                if len(self._describe(pairs[position][1])[0]) == count:
                    todo.setdefault(count, []).append(position)
                else:
                    todo.setdefault(-position - 1, []).append(position)
        for positions in todo.values():
            for start in range(0, len(positions), self.batch_size):
                batch = positions[start : start + self.batch_size]
                first = [self._describe(pairs[i][0]) for i in batch]
                second = [self._describe(pairs[i][1]) for i in batch]
                data = {
                    f"image{side}": {
                        "keypoints": torch.stack([d[0] for d in described]),
                        "descriptors": torch.stack([d[1] for d in described]),
                        "image_size": torch.stack([d[2] for d in described]),
                    }
                    for side, described in enumerate((first, second))
                }
                with torch.inference_mode():
                    scores = self.glue(data)["matching_scores0"]
                counts = (scores >= self.confidence).sum(dim=1).cpu().tolist()
                for position, count in zip(batch, counts, strict=True):
                    self._counts[keys[position]] = float(count)
        if todo and self._cache is not None:
            self._cache.parent.mkdir(parents=True, exist_ok=True)
            self._cache.write_text(json.dumps(self._counts), encoding="utf-8")
        return np.array([self._counts[key] for key in keys], dtype=np.float32)
