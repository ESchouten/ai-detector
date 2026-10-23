import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from reid.manifest import Crop


class FakeMatcher:
    """Pictures of one cow share many coat details, of different cows few."""

    name = "fake-matcher"

    def __init__(self):
        self.pairs = []

    def matches(self, pairs):
        self.pairs.extend(pairs)
        return np.array(
            [100.0 if Path(a).parent == Path(b).parent else 5.0 for a, b in pairs],
            dtype=np.float32,
        )


class FakeEmbedder:
    """Each animal points one way; pictures scatter a little around it."""

    def __init__(self, dimensions: int = 16, noise: float = 0.15, seed: int = 0):
        self.name = "fake"
        self.device = SimpleNamespace(type="fake")
        self.calls = 0
        self.noise = noise
        self.dimensions = dimensions
        self.seed = seed

    def embed(self, paths):
        self.calls += 1
        rows = []
        for path in paths:
            identity = path.parent.name
            direction = np.random.default_rng(
                zlib.crc32(f"{self.seed}:{identity}".encode())
            ).normal(size=self.dimensions)
            jitter = np.random.default_rng(zlib.crc32(path.name.encode())).normal(
                size=self.dimensions
            )
            row = direction / np.linalg.norm(direction) + self.noise * jitter
            rows.append(row / np.linalg.norm(row))
        return np.asarray(rows, dtype=np.float32)


@pytest.fixture
def herd(tmp_path: Path) -> list[Crop]:
    """Eight cows over four days, two tracks a day, small real pictures."""
    crops = []
    for cow in range(8):
        folder = tmp_path / f"cow{cow}"
        folder.mkdir()
        for day in range(4):
            for track in range(2):
                for picture in range(3):
                    path = folder / f"d{day}-t{track}-{picture}.png"
                    Image.new("RGB", (8, 8), (cow * 30, day * 60, picture)).save(path)
                    crops.append(
                        Crop(
                            path,
                            f"cow{cow}",
                            f"2026-10-0{day + 1}",
                            "camera",
                            f"cow{cow}-d{day}-t{track}",
                            night=track == 1,
                        )
                    )
    return crops
