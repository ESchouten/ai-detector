"""Train a small cattle metric head using external identities only.

Checkpoint selection uses the external identity/date-disjoint validation panel.
Eight-calves and ETHZ are transfer diagnostics only and never select an epoch.
"""

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from recognition_experiment import calibrate_target
from recognition_finetune import supervised_contrastive
from safetensors.torch import load_file, save_file
from scoring import metrics, normalize, score


class MetricHead(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.network = torch.nn.Sequential(
            torch.nn.Linear(2152, 512, bias=False),
            torch.nn.LayerNorm(512),
            torch.nn.GELU(),
            torch.nn.Dropout(0.1),
            torch.nn.Linear(512, 256, bias=False),
        )

    def forward(self, values):
        return torch.nn.functional.normalize(self.network(values), dim=1)


def transform(head, vectors):
    head.eval()
    with torch.inference_mode():
        return np.concatenate(
            [
                head(torch.from_numpy(values.astype(np.float32))).numpy()
                for values in np.array_split(
                    vectors, max(1, math.ceil(len(vectors) / 256))
                )
            ]
        )


def load_head(path):
    head = MetricHead().eval()
    head.load_state_dict(load_file(str(path)), strict=True)
    return head


def blend_features(original, learned, weight):
    if weight == 1:
        return learned
    return normalize(
        np.concatenate(
            [np.sqrt(1 - weight) * original, np.sqrt(weight) * learned], axis=1
        )
    )


def validation(rows, vectors):
    identities = sorted({row["identity"] for row in rows})
    labels = np.array([identities.index(row["identity"]) for row in rows])
    gallery = np.array([row["split"] == "validation_gallery" for row in rows])
    queries = np.array([row["split"] == "validation_query" for row in rows])
    scores = score(
        vectors[gallery],
        labels[gallery],
        vectors[queries],
        labels[queries],
        np.zeros(queries.sum()),
    )
    threshold, margin = calibrate_target(scores)
    result = {
        "threshold": threshold,
        "margin": margin,
        **metrics(scores, threshold, margin),
    }
    result["datasets"] = {}
    for dataset in sorted({row["dataset"] for row in rows}):
        positions = [i for i, row in enumerate(rows) if row["dataset"] == dataset]
        if len(positions) != len(rows):
            result["datasets"][dataset] = validation(
                [rows[i] for i in positions], vectors[positions]
            )
    return result


def checkpoint(head, rows, vectors, output, epoch):
    path = output / f"head-{epoch:02d}.safetensors"
    save_file(head.state_dict(), str(path))
    learned = transform(head, vectors)
    result = [
        {
            "epoch": epoch,
            "head_weight": weight,
            "weights_sha256": digest(path),
            "validation": validation(rows, blend_features(vectors, learned, weight)),
        }
        for weight in (0.25, 0.5, 1.0)
    ]
    print(json.dumps(result), flush=True)
    return result


def train(args):
    torch.set_num_threads(2)
    torch.manual_seed(42)
    random.seed(42)
    manifest = json.loads((args.features / "manifest.json").read_text())
    if digest(args.features / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Public-cohort feature archive changed")
    with np.load(args.features / "vectors.npz", allow_pickle=False) as archive:
        vectors = normalize(archive["vectors"])
    rows = manifest["rows"]
    train_rows = [i for i, row in enumerate(rows) if row["split"] == "train"]
    identities = sorted({rows[i]["identity"] for i in train_rows})
    groups = [
        [i for i in train_rows if rows[i]["identity"] == identity]
        for identity in identities
    ]
    validation_ids = {row["identity"] for row in rows if row["split"] != "train"}
    if set(identities) & validation_ids:
        raise ValueError("Training and validation identities overlap")
    head = MetricHead()
    classifier = torch.nn.Linear(256, len(identities), bias=False)
    optimizer = torch.optim.AdamW(
        list(head.parameters()) + list(classifier.parameters()),
        lr=1e-3,
        weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=50, eta_min=1e-5
    )
    args.output.mkdir(parents=True, exist_ok=True)
    protocol = {
        "features_manifest_sha256": digest(args.features / "manifest.json"),
        "encoder_fingerprint": manifest["contract"]["encoder_fingerprint"],
        "architecture": "2152→512 LayerNorm/GELU/dropout0.1→256 L2",
        "seed": 42,
        "epochs": 50,
        "batch": "24 identities × 4 samples from different days",
        "loss": "SupervisedContrastive0.1 +0.25cosine-margin classifier(margin0.2, temperature0.1)",
        "augmentation": "Training feature dropout0.1 and Gaussian0.001; no query augmentation",
        "checkpoint_epochs": [10, 25, 50],
        "learned_feature_weights": [0.25, 0.5, 1.0],
        "baseline_eligible_for_selection": True,
        "selection": "External validation correct accepts under99%precision/1%unknownFA, then known rank1; no transfer-panel epoch selection",
        "sources": manifest["contract"],
    }
    write_json(args.output / "protocol.json", protocol)
    baseline = validation(rows, vectors)
    print(json.dumps({"baseline": baseline}), flush=True)
    checkpoints = []
    for epoch in range(1, 51):
        head.train()
        losses = []
        for _ in range(math.ceil(len(train_rows) / 96)):
            chosen = random.sample(range(len(groups)), 24)
            positions = [
                i for identity in chosen for i in random.sample(groups[identity], 4)
            ]
            labels = torch.tensor(chosen).repeat_interleave(4)
            values = torch.from_numpy(vectors[positions].copy())
            values = torch.nn.functional.normalize(
                torch.nn.functional.dropout(values, p=0.1, training=True)
                + 0.001 * torch.randn_like(values),
                dim=1,
            )
            optimizer.zero_grad(set_to_none=True)
            encoded = head(values)
            logits = torch.nn.functional.linear(
                encoded, torch.nn.functional.normalize(classifier.weight, dim=1)
            )
            logits[torch.arange(len(labels)), labels] -= 0.2
            loss = supervised_contrastive(
                encoded, labels
            ) + 0.25 * torch.nn.functional.cross_entropy(logits / 0.1, labels)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        scheduler.step()
        if epoch % 5 == 0:
            print(
                json.dumps({"epoch": epoch, "loss": float(np.mean(losses))}), flush=True
            )
        if epoch in (10, 25, 50):
            checkpoints.extend(checkpoint(head, rows, vectors, args.output, epoch))
    selected = max(
        [{"epoch": 0, "head_weight": 0, "validation": baseline}, *checkpoints],
        key=lambda record: (
            record["validation"]["correct_accepts"],
            record["validation"]["known_rank1"],
        ),
    )
    write_json(
        args.output / "report.json",
        {
            "protocol": protocol,
            "baseline": baseline,
            "checkpoints": checkpoints,
            "selected": selected,
        },
    )
    print(json.dumps({"selected_epoch": selected["epoch"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    train(parser.parse_args())


if __name__ == "__main__":
    main()
