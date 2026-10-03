"""CPU-only, network-denied proof of a small patched upstream Cutie wheel."""

import argparse
import email
import hashlib
import importlib.metadata
import importlib.resources
import inspect
import json
import os
import sys
import time
import zipfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wheel_contents(path, upstream):
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        metadata = email.message_from_bytes(
            wheel.read(next(p for p in names if p.endswith(".dist-info/METADATA")))
        )
        requirements = metadata.get_all("Requires-Dist")
        assert set(requirements) == {
            "hydra-core>=1.3.2",
            "numpy>=1.21",
            "torch>=2.0",
        }
        configs = sorted(p for p in names if p.endswith(".yaml"))
        expected_configs = sorted(
            str(p.relative_to(upstream))
            for p in (upstream / "cutie/config").rglob("*.yaml")
        )
        assert configs == expected_configs
        changed = []
        for name in names:
            if (
                name.startswith("cutie/")
                and wheel.read(name) != (upstream / name).read_bytes()
            ):
                changed.append(name)
        assert changed == ["cutie/model/big_modules.py"]
        license_name = next(p for p in names if p.endswith("/licenses/LICENSE"))
        assert wheel.read(license_name) == (upstream / "LICENSE").read_bytes()
        return {
            "wheel_sha256": digest(path),
            "wheel_bytes": path.stat().st_size,
            "requires_dist": requirements,
            "unchanged_yaml_files": configs,
            "changed_package_files": changed,
            "license_sha256": digest(upstream / "LICENSE"),
        }


def check_default_initialization(model_type, config, attempts):
    """The optional flag preserves the library's existing training behavior."""
    del config.model.pretrained_backbone
    try:
        model_type(config)
    except RuntimeError as error:
        assert "Network disabled" in str(error)
    else:
        raise AssertionError("The absent flag no longer requests upstream weights")
    assert attempts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "installed", "upstream", "checkpoint", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    report = wheel_contents(args.wheel, args.upstream)
    cache = args.output.parent / "empty-torch-cache"
    cache.mkdir(parents=True, exist_ok=False)
    os.environ["TORCH_HOME"] = str(cache)
    attempts = []

    def deny_network(event, arguments):
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo"}:
            attempts.append(event)
            raise RuntimeError("Network disabled by the isolated CPU packaging proof")

    sys.addaudithook(deny_network)
    import torch
    from cutie.inference.inference_core import InferenceCore
    from cutie.model.cutie import CUTIE
    from hydra import compose, initialize_config_dir
    from omegaconf import OmegaConf

    assert Path(inspect.getfile(CUTIE)).is_relative_to(args.installed)
    torch.set_num_threads(2)
    config_path = str(importlib.resources.files("cutie") / "config")
    with initialize_config_dir(version_base="1.3.2", config_dir=config_path):
        config = compose(config_name="eval_config")
    config.max_internal_size = 480
    config.mem_every = 5
    config.use_long_term = True
    OmegaConf.update(config, "model.pretrained_backbone", False, force_add=True)
    OmegaConf.update(config, "model.resnet_model_path", str(cache), force_add=True)
    started = time.perf_counter()
    model = CUTIE(config).eval()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    result = model.load_state_dict(checkpoint, strict=True)
    assert not result.missing_keys and not result.unexpected_keys
    state = model.state_dict()
    assert set(state) == set(checkpoint)
    assert all(torch.equal(state[key], checkpoint[key]) for key in state)
    assert not attempts
    core = InferenceCore(model, config)
    assert core.network is model
    assert all(parameter.device.type == "cpu" for parameter in model.parameters())
    report.update(
        checkpoint_sha256=digest(args.checkpoint),
        checkpoint_tensors=len(checkpoint),
        parameter_count=sum(parameter.numel() for parameter in model.parameters()),
        strict_state_dict_and_tensor_equality=True,
        construction_and_load_seconds=time.perf_counter() - started,
        inference_core_constructed=True,
        actual_device="cpu",
        constructor_network_attempts=list(attempts),
        libraries={
            name: importlib.metadata.version(name)
            for name in ("cutie", "torch", "numpy", "hydra-core", "omegaconf")
        },
        unused_optional_imports={
            name: name in sys.modules
            for name in ("einops", "gradio", "PySide6", "thinplate", "tensorboard")
        },
    )
    assert not any(report["unused_optional_imports"].values())
    check_default_initialization(CUTIE, config, attempts)
    report["default_flag_network_request_blocked"] = list(attempts)
    report["scope"] = (
        "Isolated wheel constructor/checkpoint proof only. No GPU, camera input, "
        "production install, publication or inference-equivalence claim."
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
