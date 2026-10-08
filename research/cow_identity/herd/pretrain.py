"""Teach a backbone to tell cows apart using other farms' public photographs.

No animal of the evaluated herd is shown. The result is a starting point that a
farm's own model is adapted from, in place of the general-purpose weights.
"""

import argparse
import json
from pathlib import Path

from finetune import save, train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Manifest written by auxiliary.py")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backbone", default="dinov2-s")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--rate", type=float, default=3e-5)
    arguments = parser.parse_args()
    rows = json.loads(arguments.manifest.read_text())
    settings = {
        "backbone": arguments.backbone,
        "size": 224,
        "epochs": arguments.epochs,
        "rate": arguments.rate,
    }
    network, classes = train(
        [str(arguments.manifest.parent / row["path"]) for row in rows],
        [row["identity"] for row in rows],
        **settings,
    )
    save(network, classes, settings, arguments.output)
    export(arguments.output)
    print(arguments.output, len(classes), "cows", len(rows), "photographs")


def export(checkpoint):
    """The backbone and projection alone, in the format the application loads.

    The directions belong to the other farms' cows and are left out: a herd
    model starts its own.
    """
    import torch
    from safetensors.torch import save_file

    state = torch.load(checkpoint, map_location="cpu", weights_only=True)["state"]
    del state["directions"]
    target = Path(checkpoint).with_suffix(".safetensors")
    save_file(state, str(target))
    return target


if __name__ == "__main__":
    main()
