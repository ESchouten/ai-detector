"""Score every detector crop of a video against a herd model.

The model is trained from publisher crops of the enrolled cows only, taken on
days other than the video's own day (development) or strictly before it (final
evaluation). Output: one similarity per enrolled cow for every crop.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from ethz import VIDEOS, confirmed_before
from finetune import describe, directions, load, run_key, save, train


def fewer_confirmations(rows, per_cow, seed=0):
    """Keep the crops of `per_cow` randomly chosen clips of every cow."""
    generator = np.random.default_rng(seed)
    kept = set()
    for cow in sorted({row["cow"] for row in rows}):
        clips = sorted({row["clip"] for row in rows if row["cow"] == cow})
        chosen = generator.choice(clips, size=min(per_cow, len(clips)), replace=False)
        kept.update((cow, clip) for clip in chosen)
    return [row for row in rows if (row["cow"], row["clip"]) in kept]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--video", required=True, choices=sorted(VIDEOS))
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--enrolled", type=int, nargs="+", required=True)
    parser.add_argument(
        "--either-side",
        action="store_true",
        help="Development only: also learn from photographs taken after the video",
    )
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--backbone", default="dinov2-s")
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--rate", type=float, default=3e-5)
    parser.add_argument("--margin", type=float, default=0.25)
    parser.add_argument("--scale", type=float, default=24.0)
    parser.add_argument("--turn", type=float, default=20.0)
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument("--head-rate", type=float, default=1e-3)
    parser.add_argument("--others", type=Path, help="Manifest of other farms' cows")
    parser.add_argument("--start", type=Path, help="Checkpoint written by pretrain.py")
    parser.add_argument("--anchor", action="store_true", help="Keep its cows as rivals")
    parser.add_argument("--min-steps", type=int, default=0)
    parser.add_argument(
        "--confirmations",
        type=int,
        help="Use only this many recorded clips per cow; one clip is one confirmation",
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    rows = confirmed_before(
        json.loads(arguments.manifest.read_text()),
        arguments.video,
        set(arguments.enrolled),
        either_side=arguments.either_side,
    )
    if arguments.confirmations:
        rows = fewer_confirmations(rows, arguments.confirmations)
    root = arguments.manifest.parent
    paths = [str(root / row["path"]) for row in rows]
    labels = [row["cow"] for row in rows]
    settings = {
        "backbone": arguments.backbone,
        "size": arguments.size,
        "epochs": arguments.epochs,
        "rate": arguments.rate,
        "margin": arguments.margin,
        "scale": arguments.scale,
        "turn": arguments.turn,
        "mirror": arguments.mirror,
        "head_rate": arguments.head_rate,
    }
    others = None
    if arguments.others:
        foreign = json.loads(arguments.others.read_text())
        others = (
            [str(arguments.others.parent / row["path"]) for row in foreign],
            [row["identity"] for row in foreign],
        )
        settings["others"] = f"{arguments.others.name}:{len(foreign)}"
    if arguments.start:
        settings["start"] = str(arguments.start)
    if arguments.anchor:
        settings["anchor"] = True
    if arguments.min_steps:
        settings["min_steps"] = arguments.min_steps
    key = run_key(paths, labels, settings)
    checkpoint = arguments.cache / f"herd-{key}.pt"
    if checkpoint.exists():
        network, classes, _ = load(checkpoint)
    else:
        network, classes = train(
            paths,
            labels,
            others=others,
            **{name: value for name, value in settings.items() if name != "others"},
        )
        save(network, classes, settings, checkpoint)
    crops = json.loads((arguments.crops / "crops.json").read_text())
    vectors = describe(
        network, [str(arguments.crops / crop["path"]) for crop in crops], arguments.size
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    everything = vectors @ directions(network).T
    np.savez(
        arguments.output,
        scores=everything[:, : len(classes)],
        # Best match among classes that can never be named: other farms' cows.
        rival=everything[:, len(classes) :].max(1)
        if everything.shape[1] > len(classes)
        else np.full(len(vectors), -1.0, dtype=np.float32),
        classes=np.array(classes),
        vectors=vectors,
    )
    summary = {
        "video": arguments.video,
        "model": key,
        "training_crops": len(paths),
        "confirmations": len({(row["cow"], row["clip"]) for row in rows}),
        "training_days": sorted({row["date"] for row in rows}),
        "classes": classes,
        "crops": len(crops),
    }
    arguments.output.with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
