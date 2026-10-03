"""Bounded 60-photo MIEWid adaptation; never reads the reserved final windows."""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from safetensors.torch import save_file
from torchvision import transforms

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json
from recognition_experiment import select_gallery
from recognition_features import adapted_fingerprint
from recognition_projection import evaluate
from scoring import score

from aidetector.adapters.inference.miewid import MiewidEncoder


def supervised_contrastive(vectors, labels, temperature=0.1):
    logits = vectors @ vectors.T / temperature
    diagonal = torch.eye(len(labels), device=labels.device, dtype=torch.bool)
    positives = (labels[:, None] == labels[None, :]) & ~diagonal
    logits = logits.masked_fill(diagonal, -1e9)
    log_probability = logits - logits.logsumexp(dim=1, keepdim=True)
    return -((log_probability * positives).sum(dim=1) / positives.sum(dim=1)).mean()


def load_crops(video, rows):
    capture = cv2.VideoCapture(str(video))
    images = []
    try:
        for row in rows:
            capture.set(cv2.CAP_PROP_POS_FRAMES, row["frame"] - 1)
            success, frame = capture.read()
            if not success:
                raise ValueError("Recorded public-video frame is unavailable")
            x1, y1, x2, y2 = row["box"]
            images.append(frame[y1:y2, x1:x2].copy())
    finally:
        capture.release()
    return images


def prepare(args):
    manifest = json.loads((args.run / "manifest.json").read_text())
    if digest(args.video) != manifest["contract"]["video_sha256"]:
        raise ValueError("Public video changed")
    with np.load(args.run / "vectors.npz", allow_pickle=False) as archive:
        original = archive["vectors"]
    selected = select_gallery(manifest["rows"], original, "diverse10")
    positions = selected.tolist() + [
        i
        for i, row in enumerate(manifest["rows"])
        if row["panel"] != "enrollment" and row["second"] % 5 == 0
    ]
    rows = [manifest["rows"][i] for i in positions]
    return manifest, selected, positions, rows, load_crops(args.video, rows)


def evaluate_checkpoint(encoder, args, epoch, manifest, positions, rows, images):
    directory = args.output / f"epoch-{epoch:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / "model.safetensors"
    save_file(
        {
            name: value.detach().cpu().contiguous()
            for name, value in encoder.model.state_dict().items()
        },
        str(checkpoint),
    )
    fingerprint = adapted_fingerprint(
        manifest["contract"]["encoder_fingerprint"], checkpoint
    )
    vectors = np.concatenate(
        [
            encoder.encode(images[start : start + 8])
            for start in range(0, len(images), 8)
        ]
    )
    np.savez_compressed(directory / "vectors.npz", vectors=vectors)
    write_json(
        directory / "manifest.json",
        {
            "contract": {
                **manifest["contract"],
                "encoder_fingerprint": fingerprint,
                "adapted_weights_sha256": digest(checkpoint),
                "panels": {
                    name: sorted(
                        {row["second"] for row in rows if row["panel"] == name}
                    )
                    for name in {row["panel"] for row in rows}
                },
            },
            "rows": rows,
            "original_rows": positions,
            "vectors_sha256": digest(directory / "vectors.npz"),
            "base_manifest_sha256": digest(args.run / "manifest.json"),
        },
    )
    gallery = vectors[:60]
    labels = np.array([row["cow"] for row in rows[:60]])

    def predictor(queries, truth):
        return score(gallery, labels, queries, truth, np.zeros(len(truth)))

    results = {"single_frame": evaluate(rows, vectors, predictor, 1)}
    write_json(
        directory / "report.json",
        {
            "base_contract": manifest["contract"],
            "original_rows": positions,
            "rows": rows,
            "weights_sha256": digest(checkpoint),
            "vectors_sha256": digest(directory / "vectors.npz"),
            "results": results,
            "limitation": "Oracle crops, 5-second query spacing; single-frame recognition only",
        },
    )
    print(
        json.dumps(
            {
                "epoch": epoch,
                "metrics": {
                    name: condition["panels"] for name, condition in results.items()
                },
            }
        ),
        flush=True,
    )


def train(args):
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    manifest, selected, positions, rows, images = prepare(args)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(
        args.output / "protocol.json",
        {
            "base_manifest_sha256": digest(args.run / "manifest.json"),
            "train_rows": selected.tolist(),
            "training_examples": len(selected),
            "unknown_ids_excluded": [7, 8],
            "seed": 42,
            "epochs": 15,
            "steps_per_epoch": 10,
            "batch": "6 identities × 2 independent reference augmentations",
            "loss": "supervised contrastive temperature0.1 + 0.25cosine classifier crossentropy",
            "optimizer": "AdamW lr1e-5, classifier1e-3, weight_decay1e-4",
            "trainable": "Last EfficientNet block and conv head only; all BN running statistics frozen",
            "checkpoints": [5, 15],
            "evaluation": "Every5seconds development/calibration only; final windows absent",
            "augmentation": "Quarter turns, horizontal flip, random crop scale0.85–1.0 ratio0.85–1.15, brightness/contrast0.15/saturation0.1",
        },
    )
    encoder = MiewidEncoder(
        args.output / "models", device=args.device, weights=args.weights
    )
    model = encoder.model
    model.backbone.blocks[-1][-1].requires_grad_(True)
    model.backbone.conv_head.requires_grad_(True)
    classifier = torch.nn.Linear(encoder.dimension, 6, bias=False).to(args.device)
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for p in model.parameters() if p.requires_grad], "lr": 1e-5},
            {"params": classifier.parameters(), "lr": 1e-3},
        ],
        weight_decay=1e-4,
    )
    augmentation = transforms.Compose(
        [
            transforms.Resize((440, 440)),
            transforms.RandomResizedCrop(
                (440, 440), scale=(0.85, 1.0), ratio=(0.85, 1.15)
            ),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1),
            transforms.ToTensor(),
            transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
        ]
    )
    grouped = {
        cow: [i for i, row in enumerate(rows[:60]) if row["cow"] == cow]
        for cow in range(1, 7)
    }
    labels = torch.arange(6, device=args.device).repeat_interleave(2)
    started = time.perf_counter()
    for epoch in range(1, 16):
        losses = []
        for _ in range(10):
            batch = []
            for cow in range(1, 7):
                for index in random.sample(grouped[cow], 2):
                    rgb = np.rot90(
                        images[index][:, :, ::-1], random.randrange(4)
                    ).copy()
                    batch.append(augmentation(Image.fromarray(rgb)))
            optimizer.zero_grad(set_to_none=True)
            vectors = torch.nn.functional.normalize(
                model(torch.stack(batch).to(args.device)), dim=1
            )
            logits = (
                torch.nn.functional.linear(
                    vectors, torch.nn.functional.normalize(classifier.weight, dim=1)
                )
                / 0.1
            )
            loss = supervised_contrastive(
                vectors, labels
            ) + 0.25 * torch.nn.functional.cross_entropy(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 5
            )
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        print(
            json.dumps(
                {
                    "epoch": epoch,
                    "loss": float(np.mean(losses)),
                    "seconds": time.perf_counter() - started,
                }
            ),
            flush=True,
        )
        if epoch in (5, 15):
            evaluate_checkpoint(encoder, args, epoch, manifest, positions, rows, images)
    write_json(
        args.output / "completion.json", {"seconds": time.perf_counter() - started}
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    train(parser.parse_args())


if __name__ == "__main__":
    main()
