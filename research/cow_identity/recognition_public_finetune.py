"""Bounded image-level cattle adaptation with separate training and selection.

The default 200-step pilot updates the visual backbone, unlike the earlier
feature-head control. An explicit enrollment archive adds60 early masked calf
references and defers checkpoint selection to the frozen farm-study protocol.
"""

import argparse
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from benchmark import digest, write_json
from PIL import Image
from recognition_farm_data import load_training
from recognition_features import adapted_fingerprint
from recognition_finetune import MiewidEncoder, supervised_contrastive
from recognition_public_head import validation
from safetensors.torch import save_file
from torchvision import transforms


def training_groups(rows):
    training = [row for row in rows if row["split"] == "train"]
    identities = sorted({row["identity"] for row in training})
    held_out = {row["identity"] for row in rows if row["split"] != "train"}
    if held_out & set(identities):
        raise ValueError("Training and validation identities overlap")
    groups = {
        identity: [row for row in training if row["identity"] == identity]
        for identity in identities
    }
    for identity, group in groups.items():
        if len({row["day"] for row in group}) != len(group):
            raise ValueError(f"Multiple same-day training photos for {identity}")
    datasets = {
        dataset: [
            identity
            for identity, group in groups.items()
            if group[0]["dataset"] == dataset
        ]
        for dataset in sorted({row["dataset"] for row in training})
    }
    return identities, groups, datasets


def sample_batch(groups, datasets, rng):
    return [
        row
        for identities in datasets.values()
        for identity in rng.sample(identities, 2)
        for row in rng.sample(groups[identity], 2)
    ]


def prototype_weights(rows, vectors, identities):
    return np.stack(
        [
            vectors[
                [
                    i
                    for i, row in enumerate(rows)
                    if row["split"] == "train" and row["identity"] == identity
                ]
            ].mean(axis=0)
            for identity in identities
        ]
    )


def enrollment_data(args, rows, features):
    if args.enrollment is None:
        return rows, None
    farm, vectors = load_training(args.enrollment)
    if (
        farm["contract"]["base_encoder_fingerprint"]
        != features["contract"]["encoder_fingerprint"]
    ):
        raise ValueError("Enrollment and public prototype encoders differ")
    with np.load(args.features / "vectors.npz", allow_pickle=False) as archive:
        original = archive["vectors"].copy()
    return rows + farm["rows"], np.concatenate([original, vectors])


def evaluation(encoder, rows, images, output, step, base_fingerprint):
    encoder.model.eval()
    encoder.model.backbone.set_grad_checkpointing(False)
    directory = output / f"step-{step:03d}"
    directory.mkdir()
    checkpoint = directory / "model.safetensors"
    save_file(
        {
            name: tensor.detach().cpu().contiguous()
            for name, tensor in encoder.model.state_dict().items()
        },
        str(checkpoint),
    )
    vectors = np.concatenate(
        [encoder.encode(images[i : i + 8]) for i in range(0, len(images), 8)]
    )
    np.savez_compressed(directory / "vectors.npz", vectors=vectors)
    result = {
        "step": step,
        "weights_sha256": digest(checkpoint),
        "encoder_fingerprint": adapted_fingerprint(base_fingerprint, checkpoint),
        "validation": validation(rows, vectors),
    }
    write_json(
        directory / "manifest.json",
        {
            "contract": {
                "encoder_fingerprint": result["encoder_fingerprint"],
                "base_encoder_fingerprint": base_fingerprint,
                "protocol_sha256": digest(output / "protocol.json"),
            },
            "rows": rows,
            "vectors_sha256": digest(directory / "vectors.npz"),
        },
    )
    write_json(directory / "report.json", result)
    print(json.dumps(result), flush=True)
    return result


def selection_key(result):
    return (
        result["validation"]["correct_accepts"],
        result["validation"]["known_rank1"],
    )


def load_cohort(args):
    cohort = json.loads(args.cohort.read_text())
    features = json.loads((args.features / "manifest.json").read_text())
    if digest(args.cohort) != features["contract"]["cohort_manifest_sha256"]:
        raise ValueError("Public cohort differs from the cached baseline")
    if digest(args.features / "vectors.npz") != features["vectors_sha256"]:
        raise ValueError("Baseline feature archive changed")
    rows = cohort["rows"]
    if rows != features["rows"]:
        raise ValueError("Baseline rows differ from the training cohort")
    for row in rows:
        if digest(Path(row["path"])) != row["sha256"]:
            raise ValueError(f"Public training image changed: {row['path']}")
    return rows, features


def validation_data(rows, features):
    positions = [i for i, row in enumerate(rows) if row["split"] != "train"]
    validation_rows = [rows[i] for i in positions]
    images = [cv2.imread(row["path"]) for row in validation_rows]
    with np.load(features / "vectors.npz", allow_pickle=False) as archive:
        baseline = {
            "step": 0,
            "validation": validation(validation_rows, archive["vectors"][positions]),
        }
    return validation_rows, images, baseline


def training_components(encoder, identities, rows, prototypes, device):
    model = encoder.model
    model.backbone.requires_grad_(True)
    model.bn.requires_grad_(True)
    trainable = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    classifier = torch.nn.Linear(encoder.dimension, len(identities), bias=False).to(
        device
    )
    if prototypes is not None:
        with torch.no_grad():
            classifier.weight.copy_(
                torch.from_numpy(prototype_weights(rows, prototypes, identities)).to(
                    device
                )
            )
    optimizer = torch.optim.AdamW(
        [
            {"params": trainable, "lr": 1e-5},
            {"params": classifier.parameters(), "lr": 1e-3},
        ],
        weight_decay=1e-4,
    )
    augmentation = transforms.Compose(
        [
            transforms.Resize((440, 440)),
            transforms.RandomResizedCrop((440, 440), scale=(0.9, 1), ratio=(0.9, 1.1)),
            transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1),
            transforms.RandomGrayscale(p=0.1),
            transforms.ToTensor(),
            transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
        ]
    )
    return classifier, optimizer, augmentation


def train(args):
    torch.set_num_threads(2)
    torch.manual_seed(42)
    random.seed(42)
    rng = random.Random(42)
    rows, features = load_cohort(args)
    validation_rows, images, baseline = validation_data(rows, args.features)
    rows, prototypes = enrollment_data(args, rows, features)
    identities, groups, datasets = training_groups(rows)
    if args.enrollment is not None:
        datasets = {
            "enrollment": datasets["enrollment"],
            "public": [
                identity
                for identity in identities
                if groups[identity][0]["dataset"] != "enrollment"
            ],
        }
    labels_by_identity = {identity: i for i, identity in enumerate(identities)}
    args.output.mkdir(parents=True, exist_ok=False)
    encoder = MiewidEncoder(args.output / "models", args.device, args.weights)
    base_fingerprint = encoder.fingerprint
    if base_fingerprint != features["contract"]["encoder_fingerprint"]:
        raise ValueError("Training runtime differs from the cached baseline encoder")
    protocol = {
        "script_sha256": digest(Path(__file__)),
        "cohort_manifest_sha256": digest(args.cohort),
        "base_encoder_fingerprint": base_fingerprint,
        "base_features_manifest_sha256": digest(args.features / "manifest.json"),
        "seed": 42,
        "maximum_steps": args.steps,
        "checkpoint_steps": [i for i in (100, 200, 400, 600) if i <= args.steps],
        "continuation": "A 600-step run stops at 200 unless external validation beats the unchanged baseline",
        "training_images": sum(len(group) for group in groups.values()),
        "training_identities": len(identities),
        "batch": "2 identities per dataset, 2 distinct-day images per identity",
        "trainable": "Full EfficientNetV2 backbone, GeM and embedding BN affine; BN running statistics frozen",
        "gradient_checkpointing": True,
        "loss": "SupervisedContrastive(temperature0.1) +0.25cosine classifier crossentropy(temperature0.1)",
        "optimizer": "AdamW backbone1e-5, classifier1e-3, weight_decay1e-4; gradient norm cap5",
        "augmentation": "Resize440, crop retains90–100%, color0.15/0.15/0.1, grayscale0.1; quarter turns on top-down Cows2021 only; no flank mirroring",
        "selection": "External validation correct accepts under99%precision/1%unknownFA, then rank1; unchanged baseline eligible",
        "excluded": ["8-calves", "ETHZ", "reserved final videos"],
        "scope": "Research only; no production weights or defaults change",
    }
    if args.enrollment is not None:
        protocol.update(
            enrollment_manifest_sha256=digest(args.enrollment / "manifest.json"),
            batch="2 confirmed calf identities×2 distinct early photos +2 public identities×2 distinct-day photos",
            classifier_initialization="Means of training-only baseline descriptors; no validation/query or unknown calf vector",
            selection="Deferred: compare baseline/100/200 on frozen actual-calf calibration with external-validation regression guard",
            excluded=[
                "8-calves unknown7/8",
                "8-calves after299s",
                "ETHZ",
                "reserved final videos",
            ],
            augmentation="Resize440,crop90–100%, restrained color/grayscale; quarter turns on Cows2021 and early calf photos, no flank mirroring",
        )
    write_json(args.output / "protocol.json", protocol)
    model = encoder.model
    classifier, optimizer, augmentation = training_components(
        encoder, identities, rows, prototypes, args.device
    )
    checkpoints, losses = [], []
    started = time.perf_counter()
    for step in range(1, args.steps + 1):
        # Keep all BN running statistics fixed with small, identity-balanced batches.
        model.eval()
        model.backbone.set_grad_checkpointing(True)
        batch_rows = sample_batch(groups, datasets, rng)
        pixels = []
        for row in batch_rows:
            with Image.open(row["path"]) as source:
                image = source.convert("RGB")
                if row["dataset"] in ("cows2021", "enrollment"):
                    image = image.rotate(90 * rng.randrange(4), expand=True)
                pixels.append(augmentation(image))
        labels = torch.tensor(
            [labels_by_identity[row["identity"]] for row in batch_rows],
            device=args.device,
        )
        optimizer.zero_grad(set_to_none=True)
        vectors = torch.nn.functional.normalize(
            model(torch.stack(pixels).to(args.device)), dim=1
        )
        logits = torch.nn.functional.linear(
            vectors, torch.nn.functional.normalize(classifier.weight, dim=1)
        )
        loss = supervised_contrastive(
            vectors, labels
        ) + 0.25 * torch.nn.functional.cross_entropy(logits / 0.1, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
        if step % 20 == 0:
            print(
                json.dumps(
                    {
                        "step": step,
                        "loss": float(np.mean(losses[-20:])),
                        "elapsed_seconds": time.perf_counter() - started,
                    }
                ),
                flush=True,
            )
        if step in protocol["checkpoint_steps"]:
            checkpoints.append(
                evaluation(
                    encoder,
                    validation_rows,
                    images,
                    args.output,
                    step,
                    base_fingerprint,
                )
            )
            selected = max([baseline, *checkpoints], key=selection_key)
            write_json(
                args.output / "report.json",
                {
                    "protocol": protocol,
                    "baseline": baseline,
                    "checkpoints": checkpoints,
                    "selected": selected if args.enrollment is None else None,
                    "external_best": selected,
                    "completed_steps": step,
                    "elapsed_seconds": time.perf_counter() - started,
                },
            )
            if step == 200 and selected["step"] == 0:
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--steps", type=int, choices=(200, 600), default=200)
    parser.add_argument(
        "--enrollment",
        type=Path,
        help="Verified60-photo early masked farm archive; checkpoints require separate calibration selection",
    )
    train(parser.parse_args())


if __name__ == "__main__":
    main()
