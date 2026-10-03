"""Separate corrected teacher-forcing CPU training, preserving the earlier result."""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from eartag_trocr import (
    DATA,
    MODEL,
    RECIPE,
    checked,
    encode_labels,
    epoch_indices,
    load_model,
    optimizer_groups,
    pixels,
    processor,
)
from eartag_trocr_loss import aligned_loss

ROOT = Path(__file__).parent
BASE = ROOT / "eartag_trocr_protocol.json"


def forward_loss(model, image, labels):
    """The public model prepares shifted inputs; targets remain in their positions."""
    decoder = model.prepare_decoder_input_ids_from_labels(labels)
    output = model(pixel_values=image, decoder_input_ids=decoder)
    return aligned_loss(output.logits, labels)


def freeze(args):
    base = checked(BASE)
    paths = [
        Path(__file__),
        ROOT / "test_eartag_trocr_cpu.py",
        ROOT / "eartag_trocr_loss.py",
        ROOT / "test_eartag_trocr_loss.py",
        ROOT / "eartag_trocr_loss_protocol.json",
        ROOT / "eartag_trocr_operator_protocol.json",
        ROOT / "results/2026-10-03/ear-tags/trocr-loss.json",
        ROOT / "results/2026-10-03/ear-tags/trocr-operator.json",
        BASE,
    ]
    write_json(
        args.protocol,
        {
            **base,
            "scope": "One independently frozen correctness repair: CPUFP32 replaces discrepantMPSbackward and explicit aligned teacher-forcing CE replaces verified double-shifted defaultloss. Sameoriginalcheckpoint,3243trainlines,2epochs,812steps,alloriginalgroups and optimizationhyperparameters. No model/grid/checkpointselection. Oldnegativepreserved. No calibration/reserved images.",
            "files": {**base["files"], **{str(p): digest(p) for p in paths}},
            "base_protocol_sha256": digest(BASE),
            "correction": {
                "device": "cpu",
                "threads": 2,
                "loss": "Decoder inputs prepared once by model.prepare_decoder_input_ids_from_labels; call model WITHOUTlabels and CE(logits,originalalignedlabels), ignore_index=-100. No secondtargetshift.",
                "preflight_steps": 20,
                "preflight_maximum_seconds": 90,
                "training_maximum_seconds": 1500,
                "fresh_reset": True,
                "evaluation": "Same275preparedoracle/detectedpilotcrops, rawgreedymax32reader outputs, sameall-line/miss/extra/fulltag/CERscoring asoriginal. Reuse originalreaderrawbaseline; finalcorrectedcheckpointonly. No confidence oragreementthresholdtuning.",
            },
        },
    )


def validate(path):
    value = json.loads(path.read_text())
    checked(BASE)
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Corrected training source changed: {name}")
    return value


def step(model, optimizer, processing, rows, group):
    optimizer.zero_grad(set_to_none=True)
    total = sum(map(len, group))
    loss_sum = 0.0
    for indices in group:
        selected = [rows[i] for i in indices]
        labels = encode_labels(processing.tokenizer, [row["text"] for row in selected])
        loss = forward_loss(model, pixels(processing, selected), labels)
        if not torch.isfinite(loss):
            raise RuntimeError("Nonfinite correctedCPUloss")
        weight = len(indices) / total
        (loss * weight).backward()
        loss_sum += float(loss.detach()) * weight
    norm = torch.nn.utils.clip_grad_norm_(
        model.parameters(), RECIPE["gradient_clip"], error_if_nonfinite=True
    )
    optimizer.step()
    return loss_sum, float(norm)


def train(args):
    value = validate(args.protocol)
    torch.set_num_threads(2)
    torch.manual_seed(RECIPE["seed"])
    np.random.seed(RECIPE["seed"])
    report = {
        "protocol_sha256": digest(args.protocol),
        "base_protocol_sha256": digest(BASE),
        "mode": args.mode,
        "actual_device": "cpu",
        "precision": "float32",
        "threads": torch.get_num_threads(),
        "complete": False,
        "steps": [],
        "error": None,
    }
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    limit = value["correction"][
        "preflight_maximum_seconds"
        if args.mode == "preflight"
        else "training_maximum_seconds"
    ]
    try:
        processing = processor()
        model = load_model(MODEL, "cpu").train()
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=RECIPE["learning_rate"],
            betas=tuple(RECIPE["betas"]),
            eps=RECIPE["epsilon"],
            weight_decay=RECIPE["weight_decay"],
        )
        rows = json.loads(DATA.read_text())["panels"]["train"]
        report["optimizer_steps_per_epoch"] = math.ceil(
            math.ceil(len(rows) / RECIPE["batch"]) / RECIPE["accumulation"]
        )
        for epoch in range(RECIPE["epochs"]):
            groups = optimizer_groups(
                epoch_indices(len(rows), RECIPE["seed"], epoch),
                RECIPE["batch"],
                RECIPE["accumulation"],
            )
            for group in groups:
                tick = time.perf_counter()
                loss, norm = step(model, optimizer, processing, rows, group)
                report["steps"].append(
                    {
                        "epoch": epoch,
                        "indices": [i for batch in group for i in batch],
                        "loss": loss,
                        "gradient_norm": norm,
                        "seconds": time.perf_counter() - tick,
                    }
                )
                if len(report["steps"]) % 10 == 0:
                    print(
                        json.dumps(
                            {
                                "step": len(report["steps"]),
                                "loss": loss,
                                "gradient_norm": norm,
                                "elapsed": time.perf_counter() - started,
                            }
                        ),
                        flush=True,
                    )
                if time.perf_counter() - started > limit:
                    raise RuntimeError("FixedCPUwallbudget exceeded")
                if args.mode == "preflight" and len(report["steps"]) == 20:
                    report["complete"] = True
                    return
        model.save_pretrained(args.output / "checkpoint", safe_serialization=True)
        report["checkpoint_files"] = {
            str(p): digest(p) for p in (args.output / "checkpoint").iterdir()
        }
        report["complete"] = True
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "report.json", report)
        print(
            json.dumps({key: item for key, item in report.items() if key != "steps"}),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "preflight", "train"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("New frozen paths required")
    (freeze if args.mode == "freeze" else train)(args)
