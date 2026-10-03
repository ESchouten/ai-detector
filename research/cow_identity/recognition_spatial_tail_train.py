"""One200-step farm-specific spatial-tail checkpoint and fixed early comparison."""

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from benchmark import digest, write_json
from recognition_masked_replay import predict_panel, score_panel
from recognition_spatial_tail_data import checked, checked_parity
from recognition_spatial_tail_model import (
    contrastive_loss,
    normalized_tail,
    trainable_tail,
    validate_training_rows,
)
from safetensors.torch import load_file, save_file
from video_assessment import annotations

from aidetector.adapters.inference.miewid import MiewidEncoder


def cache_inputs(protocol_path, cache):
    protocol, descriptor, original, vectors = checked(protocol_path)
    manifest = json.loads((cache / "manifest.json").read_text())
    if (
        manifest["status"] != "COMPLETE_PARITY_PASSED_BEFORE_TRAINING"
        or manifest["protocol_sha256"] != digest(protocol_path)
        or digest(cache / "maps.npy") != manifest["maps_sha256"]
    ):
        raise ValueError("Complete immutable prefixparity prerequisite missing")
    if [r["source_index"] for r in manifest["rows"]] != protocol["source_indices"]:
        raise ValueError("Prefix observation order changed")
    expected_rows = [
        {"source_index": i, **original["rows"][i]} for i in protocol["source_indices"]
    ]
    if manifest["rows"] != expected_rows:
        raise ValueError("Prefix crop metadata changed")
    validate_prefix_parity(manifest, protocol["source_indices"])
    maps = np.load(cache / "maps.npy", mmap_mode="r", allow_pickle=False)
    if maps.shape != (len(manifest["rows"]), 328, 14, 14) or maps.dtype != np.float32:
        raise ValueError("Cached prefix shape/dtype changed")
    return protocol, descriptor, original, vectors, manifest, maps


def validate_prefix_parity(manifest, source_indices):
    comparisons = manifest["parity"]
    if not comparisons or comparisons[0]["full_split"] is None:
        raise ValueError("Full-network/split parity was not checked")
    checked_parity(comparisons[0]["full_split"])
    observed = [i for batch in comparisons for i in batch["source_indices"]]
    if sorted(observed) != source_indices:
        raise ValueError(
            "Every prefix crop must pass original descriptor parity exactly once"
        )
    for batch in comparisons:
        checked_parity(batch["original_cache"])


def freeze(args):
    protocol, _, _, _, manifest, _ = cache_inputs(args.protocol, args.cache)
    paths = [
        Path(__file__),
        args.protocol,
        args.cache / "manifest.json",
        args.cache / "maps.npy",
        Path(__file__).with_name("recognition_spatial_tail_model.py"),
        Path(__file__).with_name("recognition_masked_replay.py"),
        Path(__file__).with_name("scoring.py"),
        Path(__file__).with_name("video_assessment.py"),
        Path(__file__).with_name("test_recognition_spatial_tail_train.py"),
    ]
    paths += [
        Path("detector/src/aidetector") / name
        for name in (
            "domain/identity.py",
            "adapters/inference/identity_observations.py",
        )
    ]
    labels = {
        "annotations": "datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz",
        "source_pickle": "datasets/8-calves/video/pmfeed_4_3_16.pkl",
    }
    paths += [Path(p) for p in labels.values()]
    write_json(
        args.freeze,
        {
            "status": "FROZEN_EXACT_PREFIX_CACHE_BEFORE_OPTIMIZATION",
            "files": {str(p): digest(p) for p in paths},
            "protocol": str(args.protocol),
            "cache": str(args.cache),
            "labels": labels,
            "training": protocol["training"],
            "prefix_parity_sha256": digest(args.cache / "manifest.json"),
            "expected_rows": len(manifest["rows"]),
            "checkpoint": 200,
            "no_recipe_change": "Alltraining parameters/sampledsteps/bankindices fixed before prefixinference; this freeze binds only the completedcache/parity.",
        },
    )


def inputs(path):
    document = json.loads(path.read_text())
    for filename, expected in document["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Frozen traininginput changed: {filename}")
    values = cache_inputs(Path(document["protocol"]), Path(document["cache"]))
    if document["training"] != values[0]["training"]:
        raise ValueError("Pre-prefix trainingrecipe changed")
    return document, values


def make_encoder(descriptor, output):
    if not torch.backends.mps.is_available():
        raise RuntimeError("ActualMPS required")
    torch.set_num_threads(2)
    encoder = MiewidEncoder(
        output / "models", "mps", Path(descriptor["inputs"]["weights"])
    )
    if encoder.fingerprint != descriptor["encoder_fingerprint"]:
        raise ValueError("OriginalMIEW environment changed")
    return encoder


def unchanged_state(model, before, trainable):
    changed = [
        name
        for name, tensor in model.state_dict().items()
        if not torch.equal(tensor.detach().cpu(), before[name])
    ]
    if not set(changed) <= set(trainable):
        raise ValueError(
            "A frozenprefix/normalization/GeM/classifier parameter changed"
        )
    return changed


def optimize(model, tail, names, protocol, manifest, maps, vectors):
    lookup = {r["source_index"]: i for i, r in enumerate(manifest["rows"])}
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=1e-5, weight_decay=1e-4
    )
    history, peak = [], 0
    for step in protocol["training_steps"]:
        positions = [lookup[i] for i in step["source_indices"]]
        rows = [manifest["rows"][i] for i in positions]
        validate_training_rows(rows)
        values = torch.from_numpy(np.array(maps[positions], copy=True)).to("mps")
        base = torch.from_numpy(vectors[step["source_indices"]].copy()).to("mps")
        optimizer.zero_grad(set_to_none=True)
        encoded = normalized_tail(tail, values)
        loss = contrastive_loss(encoded, base, len(positions) // 2)
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite loss; no substitutecheckpoint")
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(
            [p for p in model.parameters() if p.requires_grad],
            max_norm=5,
            error_if_nonfinite=True,
        )
        if any(
            p.grad is not None
            for name, p in model.named_parameters()
            if name not in names
        ):
            raise ValueError("Gradient escaped frozen tail boundary")
        optimizer.step()
        peak = max(peak, torch.mps.driver_allocated_memory())
        if peak > protocol["resources"]["driver_bytes_cap"]:
            raise MemoryError("MPSbudget exceeded; retain failure")
        history.append(
            {
                "step": step["step"],
                "loss": float(loss.detach().cpu()),
                "gradient_norm_before_clip": float(gradient.detach().cpu()),
            }
        )
        if step["step"] % 25 == 0:
            print(json.dumps({**history[-1], "driver_peak": peak}), flush=True)
    return history, peak


def train(args):
    _, (protocol, descriptor, _, vectors, manifest, maps) = inputs(args.freeze)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    torch.manual_seed(42)
    encoder = make_encoder(descriptor, args.output)
    _, tail, names = trainable_tail(encoder.model)
    before = {
        name: tensor.detach().cpu().clone()
        for name, tensor in encoder.model.state_dict().items()
    }
    trainable_count = sum(
        p.numel() for p in encoder.model.parameters() if p.requires_grad
    )
    history, peak = optimize(
        encoder.model, tail, names, protocol, manifest, maps, vectors
    )
    changed = unchanged_state(encoder.model, before, names)
    if not changed or len(history) != 200:
        raise ValueError("Incomplete/no-op tail optimization")
    checkpoint = args.output / "step-200.safetensors"
    save_file(
        {
            name: tensor.detach().cpu().contiguous()
            for name, tensor in encoder.model.state_dict().items()
        },
        str(checkpoint),
    )
    write_json(
        args.output / "training.json",
        {
            "status": "COMPLETE_FIXED200",
            "freeze_sha256": digest(args.freeze),
            "checkpoint_sha256": digest(checkpoint),
            "trainable_parameter_names": names,
            "trainable_parameter_count": trainable_count,
            "changed_state_keys": changed,
            "outside_tail_changes": [],
            "steps": history,
            "elapsed_seconds": time.perf_counter() - started,
            "driver_peak": peak,
            "device": "mps",
            "precision": "float32",
        },
    )
    print(
        json.dumps(
            {
                "complete": True,
                "steps": len(history),
                "seconds": time.perf_counter() - started,
                "parameters": trainable_count,
            }
        ),
        flush=True,
    )


def transformed(tail, maps, cap):
    vectors, peak = [], 0
    with torch.inference_mode():
        for offset in range(0, len(maps), 8):
            values = torch.from_numpy(
                np.array(maps[offset : offset + 8], copy=True)
            ).to("mps")
            vectors.extend(normalized_tail(tail, values).cpu().numpy())
            peak = max(peak, torch.mps.driver_allocated_memory())
            if peak > cap:
                raise MemoryError("MPSbudget exceeded duringfixed comparison")
    return np.asarray(vectors, dtype=np.float32), peak


def evaluate(args):
    document, (protocol, descriptor, original, vectors, manifest, maps) = inputs(
        args.freeze
    )
    training = json.loads((args.output / "training.json").read_text())
    checkpoint = args.output / "step-200.safetensors"
    if training["freeze_sha256"] != digest(args.freeze) or training[
        "checkpoint_sha256"
    ] != digest(checkpoint):
        raise ValueError("Fixed checkpointchanged")
    if (args.output / "calibration.json").exists():
        raise FileExistsError("Preserve completed comparison")
    encoder = make_encoder(descriptor, args.output)
    encoder.model.load_state_dict(load_file(str(checkpoint)), strict=True)
    _, tail, _ = trainable_tail(encoder.model)
    tail.eval()
    adapted, peak = transformed(tail, maps, protocol["resources"]["driver_bytes_cap"])
    lookup = {row["source_index"]: i for i, row in enumerate(manifest["rows"])}
    features = {
        "rows": manifest["rows"],
        "frames": [
            {"second": frame["second"], "rows": [lookup[i] for i in frame["rows"]]}
            for frame in original["frames"]
            if 450 <= frame["second"] <= 629
        ],
    }
    bank = [lookup[i] for i in protocol["bank_source_indices"]]
    owners = tuple(
        (
            str(manifest["rows"][i]["track_id"] + 1),
            str(manifest["rows"][i]["track_id"] + 1),
        )
        for i in bank
    )
    baseline = vectors[[r["source_index"] for r in manifest["rows"]]]
    predictions = {
        name: predict_panel(features, values, owners, values[bank], 450, 629)
        for name, values in (("untrained_bank", baseline), ("spatial_tail200", adapted))
    }
    records, _ = annotations(
        SimpleNamespace(
            **{key: Path(value) for key, value in document["labels"].items()}
        )
    )
    panels = {"untrained_bank": score_panel(predictions["untrained_bank"], records)}
    previous = json.loads(Path(protocol["baseline_report"]).read_text())
    if panels["untrained_bank"] != previous["panels"]["untrained_dense_bank"]:
        raise ValueError("Untouched96-reference baseline no longer replays exactly")
    panels["spatial_tail200"] = score_panel(predictions["spatial_tail200"], records)
    np.savez_compressed(args.output / "adapted-vectors.npz", vectors=adapted)
    report = {
        "status": "COMPLETE_FIXED_CALIBRATION",
        "freeze_sha256": digest(args.freeze),
        "training_sha256": digest(args.output / "training.json"),
        "checkpoint_sha256": digest(checkpoint),
        "adapted_vectors_sha256": digest(args.output / "adapted-vectors.npz"),
        "panels": panels,
        "baseline_exact_counter_and_timeline_parity": True,
        "driver_peak": peak,
        "all_goal_gates": {
            name: (panel["conservative_named_precision"] or 0) >= 0.99
            and panel["known_coverage"] >= 0.60
            and panel["unknown_false_naming_rate"] <= 0.01
            for name, panel in panels.items()
        },
        "limits": protocol["limits"],
        "training_scope": "Farm adaptation on all6initial-knownlineages, unknown7/8excluded; no untrained5/6claim, no laterquery.",
    }
    write_json(args.output / "calibration.json", report)
    print(
        json.dumps(
            {
                "goals": report["all_goal_gates"],
                "panels": {
                    name: {
                        key: value
                        for key, value in panel.items()
                        if key not in ("timeline", "confusion")
                    }
                    for name, panel in panels.items()
                },
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "train", "evaluate"))
    for name in ("freeze", "protocol", "cache", "output"):
        parser.add_argument(f"--{name}", type=Path, required=name == "freeze")
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.freeze.exists():
            raise FileExistsError("Preserve existing trainingfreeze")
        freeze(args)
    elif args.mode == "train":
        train(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
