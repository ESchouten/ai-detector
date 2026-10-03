"""Verify the actual vendored SDK artifact used by the optional install."""

import hashlib
import json
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

from aidetector.adapters.inference.cutie_runtime import SDK_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_vendored_cutie_matches_audited_provenance_lock_and_model_resources():
    directory = ROOT / "vendor/cutie"
    provenance = json.loads((directory / "provenance.json").read_text())
    wheel = directory / provenance["wheel"]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert digest == provenance["wheel_sha256"]
    for name, expected in provenance["files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected

    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(item for item in lock["package"] if item["name"] == "cutie")
    assert package["version"] == SDK_VERSION
    assert package["source"] == {"path": str(wheel.relative_to(ROOT))}
    assert package["wheels"][0]["hash"] == f"sha256:{digest}"
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(
            archive.read(f"cutie-{SDK_VERSION}.dist-info/METADATA")
        )
        assert metadata["Version"] == SDK_VERSION
        assert (
            archive.read(f"cutie-{SDK_VERSION}.dist-info/licenses/LICENSE")
            == (directory / "LICENSE").read_bytes()
        )
        for resource in ("eval_config.yaml", "model/base.yaml", "model/small.yaml"):
            assert archive.read(f"cutie/config/{resource}")
        assert not any(
            Path(name).suffix in {".pth", ".pt", ".safetensors", ".orig"}
            for name in archive.namelist()
        )
