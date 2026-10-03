"""One frozen residual-head pilot; only early pseudo-pairs enter optimization."""

import argparse
import json
import math
import random
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from benchmark import digest, write_json
from recognition_masked_replay import predict_panel, score_panel
from recognition_temporal_features import checked
from recognition_temporal_review import quality_rows
from safetensors.torch import load_file, save_file
from scoring import normalize
from video_assessment import annotations


class ResidualMetricHead(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.hidden = torch.nn.Sequential(
            torch.nn.Linear(2152, 256, bias=False),
            torch.nn.LayerNorm(256),
            torch.nn.GELU(),
            torch.nn.Dropout(0.1),
        )
        self.output = torch.nn.Linear(256, 2152, bias=False)
        torch.nn.init.zeros_(self.output.weight)

    def forward(self, values):
        return torch.nn.functional.normalize(
            values + 0.1 * self.output(self.hidden(values)), dim=1
        )


def indexed_groups(protocol, manifest):
    positions = {
        (r["second"], r["track_id"]): i
        for i, r in enumerate(manifest["rows"])
        if r["kind"] == "observation"
    }
    groups = []
    for group in protocol["training_groups"]:
        if len(group["pairs"]) < 2 or len(
            {p["track_id"] for p in group["pairs"]}
        ) != len(group["pairs"]):
            raise ValueError("Negatives must be distinct same-frame slots")
        anchors, positives = [], []
        for pair in group["pairs"]:
            if (
                pair["track_id"] not in range(4)
                or pair["anchor_second"] != group["second"]
                or max(pair["anchor_second"], pair["positive_second"]) > 419
            ):
                raise ValueError("Non-training observation entered optimization")
            anchors.append(positions[(pair["anchor_second"], pair["track_id"])])
            positives.append(positions[(pair["positive_second"], pair["track_id"])])
        groups.append((anchors, positives))
    return groups


def frame_loss(anchors, positives):
    """Only other anchors in this exact frame are contrastive negatives."""
    positive = (anchors * positives).sum(dim=1, keepdim=True)
    negative = anchors @ anchors.T
    negative = negative.masked_fill(torch.eye(len(anchors), dtype=torch.bool), -1e9)
    logits = torch.cat((positive, negative), dim=1) / 0.1
    return torch.nn.functional.cross_entropy(
        logits, torch.zeros(len(anchors), dtype=torch.long), reduction="none"
    )


def batch_loss(head, vectors, groups):
    positions = [
        index for anchors, positives in groups for index in (*anchors, *positives)
    ]
    base = vectors[positions]
    encoded = head(base)
    losses, offset = [], 0
    for anchors, _ in groups:
        count = len(anchors)
        losses.append(
            frame_loss(
                encoded[offset : offset + count],
                encoded[offset + count : offset + 2 * count],
            )
        )
        offset += 2 * count
    contrastive = torch.cat(losses).mean()
    regularization = (1 - (base * encoded).sum(dim=1)).mean()
    return contrastive + regularization


def read_features(directory, protocol_path):
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest["contract"]["protocol_sha256"] != digest(protocol_path)
        or digest(directory / "vectors.npz") != manifest["vectors_sha256"]
    ):
        raise ValueError("Feature provenance changed")
    with np.load(directory / "vectors.npz", allow_pickle=False) as data:
        vectors = normalize(data["vectors"])
    if vectors.shape != (len(manifest["rows"]), 2152):
        raise ValueError("Feature shape changed")
    return manifest, vectors


def diverse_bank(manifest, vectors, quality, maximum=16):
    """Existing medoid-first/farthest-first convention; only early lineage refs."""
    allowed = {
        (r["second"], r["track_id"])
        for r in quality
        if r["second"] <= 419 and r["track_id"] < 6
    }
    selected = []
    for track in range(6):
        indices = [
            i
            for i, row in enumerate(manifest["rows"])
            if row["kind"] == "observation"
            and row["track_id"] == track
            and (row["second"], track) in allowed
        ]
        if not indices:
            continue
        similarity = vectors[indices] @ vectors[indices].T
        local = [int(similarity.mean(axis=1).argmax())]
        for _ in range(min(maximum, len(indices)) - 1):
            distance = 1 - similarity[:, local].max(axis=1)
            distance[local] = -1
            local.append(int(distance.argmax()))
        selected.extend(indices[i] for i in local)
    return selected


def freeze(args):
    protocol = checked(args.protocol)
    manifest, vectors = read_features(args.features, args.protocol)
    teacher = json.loads(
        (Path(protocol["inputs"]["run"]) / "streaming.json").read_text()
    )
    bank = diverse_bank(manifest, vectors, quality_rows(teacher["timeline"]))
    files = [
        Path(__file__),
        Path(__file__).with_name("test_recognition_temporal_head.py"),
        Path(__file__).with_name("recognition_masked_replay.py"),
        args.protocol,
        args.features / "manifest.json",
        args.features / "vectors.npz",
    ]
    files += [
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
    files += [Path(p) for p in labels.values()]
    if manifest["contract"]["encoder_fingerprint"] != protocol["encoder_fingerprint"]:
        raise ValueError("Base encoder changed")
    write_json(
        args.freeze,
        {
            "status": "FROZEN_BEFORE_CPU_TRAINING_OR_CALIBRATION",
            "files": {str(p): digest(p) for p in files},
            "protocol": str(args.protocol),
            "features": str(args.features),
            "labels": labels,
            "pilot": protocol["pilot"],
            "groups": len(indexed_groups(protocol, manifest)),
            "dense_bank": {
                "indices": bank,
                "references": [
                    {
                        "source_index": i,
                        "second": manifest["rows"][i]["second"],
                        "cow": manifest["rows"][i]["track_id"] + 1,
                        "pixels_sha256": manifest["rows"][i]["pixels_sha256"],
                    }
                    for i in bank
                ],
                "selection": "One fixed untrained bank comparator: all6 initialknown quality-qualified lineagecrops0–419; max16/cow; first maximummean-cosinemedoid, then1−maximumcosinetoselected farthest-first; tieinputchronological. Only original descriptors. No truth or calibration score selection, no appgallerywrites.",
                "limits": "Lineage-derived pseudo-references, not96independent farmer confirmations. More reference views/budget than27AI-reviewed photos; this isolates view coverage as a separate comparator, not headtraining effectiveness.",
            },
            "evaluation": "Unchanged predict_panel,450..629 only; names reset; all8 visible truth+unmatchederrors; no prior seednames in matching. Labels read only after both baseline/fixedhead predictions.",
        },
    )


def inputs(path):
    freeze = json.loads(path.read_text())
    for name, expected in freeze["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen trainer input changed: {name}")
    protocol_path = Path(freeze["protocol"])
    protocol = checked(protocol_path)
    if freeze["pilot"] != protocol["pilot"]:
        raise ValueError("Pre-encoding pilot plan changed")
    manifest, vectors = read_features(Path(freeze["features"]), protocol_path)
    return freeze, protocol, manifest, vectors


def train(args):
    _, protocol, manifest, vectors = inputs(args.freeze)
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    torch.manual_seed(42)
    random.seed(42)
    started = time.perf_counter()
    head = ResidualMetricHead()
    # Only predetermined training rows enter gradient-enabled forwards.
    groups = indexed_groups(protocol, manifest)
    used = sorted({i for a, p in groups for i in (*a, *p)})
    compact = {old: new for new, old in enumerate(used)}
    groups = [([compact[i] for i in a], [compact[i] for i in p]) for a, p in groups]
    values = torch.from_numpy(vectors[used].copy())
    head.eval()
    with torch.inference_mode():
        initial_error = float((head(values[:8]) - values[:8]).abs().max())
    if initial_error > 1e-6:
        raise ValueError("Zero residual must preserve original descriptors")
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.001, weight_decay=0.0001)
    history = []
    for epoch in range(1, 21):
        head.train()
        order = random.sample(range(len(groups)), len(groups))
        losses = []
        for offset in range(0, len(order), 16):
            batch = [groups[i] for i in order[offset : offset + 16]]
            optimizer.zero_grad(set_to_none=True)
            loss = batch_loss(head, values, batch)
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite training loss; no checkpoint replacement")
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        history.append({"epoch": epoch, "loss": float(np.mean(losses))})
        print(json.dumps(history[-1]), flush=True)
    path = args.output / "head-20.safetensors"
    save_file(head.state_dict(), str(path))
    write_json(
        args.output / "training.json",
        {
            "freeze_sha256": digest(args.freeze),
            "checkpoint_sha256": digest(path),
            "initial_max_absolute_error": initial_error,
            "unique_training_rows": len(used),
            "training_source_indices": used,
            "epochs": history,
            "seconds": time.perf_counter() - started,
            "device": "cpu",
            "candidate": "Only fixedepoch20; no calibration seen during optimization",
        },
    )


def transform(head, values):
    head.eval()
    with torch.inference_mode():
        return np.concatenate(
            [
                head(torch.from_numpy(batch.copy())).numpy()
                for batch in np.array_split(values, math.ceil(len(values) / 128))
            ]
        )


def evaluate(args):
    freeze, _, manifest, vectors = inputs(args.freeze)
    training = json.loads((args.output / "training.json").read_text())
    path = args.output / "head-20.safetensors"
    if training["freeze_sha256"] != digest(args.freeze) or training[
        "checkpoint_sha256"
    ] != digest(path):
        raise ValueError("Checkpoint changed")
    if (args.output / "calibration.json").exists():
        raise FileExistsError("Preserve completed calibration")
    torch.set_num_threads(2)
    head = ResidualMetricHead()
    head.load_state_dict(load_file(str(path)), strict=True)
    selected = [i for i, r in enumerate(manifest["rows"]) if r["kind"] == "gallery"]
    owners = tuple(
        (str(manifest["rows"][i]["cow"]), str(manifest["rows"][i]["cow"]))
        for i in selected
    )
    predictions = {}
    for name, values in (
        ("baseline", vectors),
        ("residual20", transform(head, vectors)),
    ):
        predictions[name] = predict_panel(
            manifest, values, owners, values[selected], 450, 629
        )
    bank = freeze["dense_bank"]["indices"]
    bank_owners = tuple(
        (
            str(manifest["rows"][i]["track_id"] + 1),
            str(manifest["rows"][i]["track_id"] + 1),
        )
        for i in bank
    )
    predictions["untrained_dense_bank"] = predict_panel(
        manifest, vectors, bank_owners, vectors[bank], 450, 629
    )
    # No annotation-driven selection, repair, optimization or threshold fitting.
    records, _ = annotations(
        SimpleNamespace(**{key: Path(value) for key, value in freeze["labels"].items()})
    )
    panels = {name: score_panel(rows, records) for name, rows in predictions.items()}
    candidate = panels["residual20"]
    accepted = (
        (candidate["conservative_named_precision"] or 0) >= 0.99
        and candidate["unknown_false_naming_rate"] <= 0.01
        and candidate["counts"]["correct_name"]
        > panels["baseline"]["counts"]["correct_name"]
    )
    report = {
        "freeze_sha256": digest(args.freeze),
        "training_sha256": digest(args.output / "training.json"),
        "panels": panels,
        "selected": "residual20" if accepted else "baseline",
        "candidate_qualifies": accepted,
        "dense_bank": freeze["dense_bank"],
        "limits": "Exposed early within-camera calibration, four pseudo-labelledtraining animals;5/6 untrained,7/8 unknown. No late query evaluation, no refitall6, no newfarm/physicalreentry claim.",
    }
    write_json(args.output / "calibration.json", report)
    print(
        json.dumps(
            {
                "selected": report["selected"],
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
    for name in ("freeze", "protocol", "features", "output"):
        parser.add_argument(f"--{name}", type=Path, required=name == "freeze")
    args = parser.parse_args()
    if args.mode == "freeze":
        if args.freeze.exists():
            raise FileExistsError("Preserve training freeze")
        freeze(args)
    elif args.mode == "train":
        train(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
