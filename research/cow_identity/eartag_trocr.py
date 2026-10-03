"""One fixed TrOCR adaptation; training groups never include pilot groups."""

import argparse
import importlib.metadata
import inspect
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

ROOT = Path(__file__).parent
MODEL = Path(".cache/cow-ear-tags/trocr-small-printed")
DATA = Path(".cache/cow-ear-tags/trocr-lines/manifest.json")
DATA_PROTOCOL = ROOT / "eartag_trocr_data_protocol.json"
RECIPE = {
    "seed": 20261003,
    "epochs": 2,
    "batch": 4,
    "accumulation": 2,
    "learning_rate": 2e-5,
    "weight_decay": 0.01,
    "betas": [0.9, 0.999],
    "epsilon": 1e-8,
    "gradient_clip": 1.0,
    "preflight_steps": 20,
    "maximum_seconds": 1200,
    "maximum_driver_bytes": 8 * 1024**3,
    "reclaim_driver_bytes": 6 * 1024**3,
    "max_new_tokens": 32,
    "decoder_start_token_id": 2,
    "pad_token_id": 1,
}


def checked(path):
    protocol = json.loads(path.read_text())
    for name, expected in protocol["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen TrOCR input changed: {name}")
    if {
        name: importlib.metadata.version(name) for name in protocol["libraries"]
    } != protocol["libraries"]:
        raise ValueError("TrOCR environment changed")
    if protocol["recipe"] != RECIPE:
        raise ValueError("Frozen training/generation recipe changed")
    return protocol


def processor():
    return TrOCRProcessor.from_pretrained(MODEL, local_files_only=True, use_fast=False)


def encode_labels(tokenizer, texts):
    encoded = tokenizer(texts, padding=True, truncation=False, return_tensors="pt")
    if encoded.input_ids.shape[1] > RECIPE["max_new_tokens"]:
        raise ValueError("A training label would exceed the frozen token budget")
    labels = encoded.input_ids.clone()
    labels[encoded.attention_mask == 0] = -100
    return labels


def epoch_indices(count, seed, epoch):
    values = list(range(count))
    random.Random(seed + epoch).shuffle(values)
    return values


def optimizer_groups(indices, batch, accumulation):
    batches = [indices[i : i + batch] for i in range(0, len(indices), batch)]
    return [batches[i : i + accumulation] for i in range(0, len(batches), accumulation)]


def freeze(args):
    data = json.loads(DATA.read_text())
    if not data["complete"] or data["protocol_sha256"] != digest(DATA_PROTOCOL):
        raise ValueError("Require complete frozen line preparation")
    processing = processor()
    if (
        processing.tokenizer.bos_token_id,
        processing.tokenizer.eos_token_id,
        processing.tokenizer.pad_token_id,
    ) != (0, 2, 1):
        raise ValueError("Pinned tokenizer special IDs changed")
    generation = json.loads((MODEL / "generation_config.json").read_text())
    if (
        generation["decoder_start_token_id"],
        generation["eos_token_id"],
        generation["pad_token_id"],
    ) != (2, 2, 1):
        raise ValueError("Pinned decoder generation IDs changed")
    all_labels = encode_labels(
        processing.tokenizer, [row["text"] for row in data["panels"]["train"]]
    )
    if any(
        "text" in row
        for panel in ("oracle", "detected")
        for row in data["panels"][panel]
    ):
        raise ValueError("Reader inputs must not contain pilot transcripts")
    paths = [
        Path(__file__),
        ROOT / "test_eartag_trocr.py",
        ROOT / "eartag_trocr_score.py",
        ROOT / "test_eartag_trocr_score.py",
        ROOT / "eartag_ocr.py",
        ROOT / "benchmark.py",
        ROOT / "scoring.py",
        DATA,
        DATA_PROTOCOL,
        *MODEL.iterdir(),
    ]
    for value in (
        TrOCRProcessor,
        VisionEncoderDecoderModel,
        processing.image_processor.__class__,
        processing.tokenizer.__class__,
    ):
        paths.append(Path(inspect.getfile(value)))
    import transformers.models.deit.modeling_deit as deit
    import transformers.models.trocr.modeling_trocr as trocr

    paths.extend([Path(deit.__file__), Path(trocr.__file__)])
    paths.extend(Path(row["path"]) for rows in data["panels"].values() for row in rows)
    write_json(
        args.protocol,
        {
            "scope": "Single full-model FP32/MPS adaptation, two epochs. Entire pilot groups excluded. Final checkpoint only; no calibration/reserved access. Original reader and final reader are measured on the same157 oracle and118 fixed detected crops. Not automatic identity naming.",
            "files": {str(path): digest(path) for path in paths},
            "libraries": {
                name: importlib.metadata.version(name)
                for name in (
                    "torch",
                    "torchvision",
                    "transformers",
                    "safetensors",
                    "tokenizers",
                    "sentencepiece",
                    "numpy",
                    "pillow",
                )
            },
            "model_revision": "04e994ab854b0089d4929f48c2b4dbe2ce78a340",
            "recipe": RECIPE,
            "score_libraries": json.loads(DATA_PROTOCOL.read_text())["libraries"],
            "data": str(DATA),
            "training_lines": len(data["panels"]["train"]),
            "longest_label_tokens_including_special": int(
                (all_labels != -100).sum(dim=1).max()
            ),
            "preprocessing": "Original SDK quad warp/orientation PNG, RGB via Pillow, official pinned DeiT384 processor, no center crop/no augmentation. Labels verbatim, tokenizer specials included; mask padding only, never truncate.",
            "generation": "Greedy max32newtokens, one beam, no sampling, official vocabulary, decoder_start2/pad1/eos2. Save raw text and token log probabilities; no confidence threshold, roster, allowlist or correction.",
            "limits": "Preflight20optimizer steps uses training only. Fresh original model and optimizer reset for full run. Stop nonfinite loss/gradient, >8GiB driver or20minutes; synchronize/reclaim allocator only above6GiB. No model/threshold grid. Timing includes reclaim.",
        },
    )


def pixels(processing, rows):
    images = []
    for row in rows:
        path = Path(row["path"])
        if digest(path) != row["sha256"]:
            raise ValueError("Line crop changed")
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    return processing(images=images, return_tensors="pt").pixel_values


def load_model(path, device):
    model = VisionEncoderDecoderModel.from_pretrained(
        path, local_files_only=True, use_safetensors=True, attn_implementation="eager"
    ).to(device=device, dtype=torch.float32)
    model.config.decoder_start_token_id = RECIPE["decoder_start_token_id"]
    model.config.pad_token_id = RECIPE["pad_token_id"]
    model.generation_config.decoder_start_token_id = RECIPE["decoder_start_token_id"]
    model.generation_config.pad_token_id = RECIPE["pad_token_id"]
    if (
        next(model.parameters()).device.type != device
        or next(model.parameters()).dtype != torch.float32
    ):
        raise ValueError("Require actual FP32 model device")
    return model


def memory(report):
    torch.mps.synchronize()
    active, driver = (
        torch.mps.current_allocated_memory(),
        torch.mps.driver_allocated_memory(),
    )
    report["peak_active_bytes"] = max(report["peak_active_bytes"], active)
    report["peak_driver_bytes_before_reclaim"] = max(
        report["peak_driver_bytes_before_reclaim"], driver
    )
    if driver > RECIPE["reclaim_driver_bytes"]:
        torch.mps.empty_cache()
        report["cache_reclaims"] += 1
    driver_after = torch.mps.driver_allocated_memory()
    report["peak_driver_bytes_after_reclaim"] = max(
        report["peak_driver_bytes_after_reclaim"], driver_after
    )
    if driver_after > RECIPE["maximum_driver_bytes"]:
        raise RuntimeError("Metal resource budget exceeded after allocator reclamation")


def new_report(args):
    return {
        "protocol_sha256": digest(args.protocol),
        "mode": args.mode,
        "complete": False,
        "actual_device": "mps",
        "precision": "float32",
        "peak_active_bytes": 0,
        "peak_driver_bytes_before_reclaim": 0,
        "peak_driver_bytes_after_reclaim": 0,
        "cache_reclaims": 0,
        "steps": [],
        "error": None,
    }


def training_step(model, optimizer, processing, rows, group):
    optimizer.zero_grad(set_to_none=True)
    total_examples = sum(map(len, group))
    loss_sum = 0.0
    for indices in group:
        chosen = [rows[i] for i in indices]
        labels = encode_labels(
            processing.tokenizer, [row["text"] for row in chosen]
        ).to("mps")
        image = pixels(processing, chosen).to("mps")
        loss = model(pixel_values=image, labels=labels).loss
        if not torch.isfinite(loss):
            raise RuntimeError("Nonfinite training loss")
        weight = len(indices) / total_examples
        (loss * weight).backward()
        loss_sum += float(loss.detach().cpu()) * weight
        del image, labels, loss
    norm = torch.nn.utils.clip_grad_norm_(
        model.parameters(), RECIPE["gradient_clip"], error_if_nonfinite=True
    )
    optimizer.step()
    return loss_sum, float(norm.detach().cpu())


def train(args):
    frozen = checked(args.protocol)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Authorized experiment requires actual MPS")
    torch.set_num_threads(2)
    torch.manual_seed(RECIPE["seed"])
    np.random.seed(RECIPE["seed"])
    report = new_report(args)
    started = time.perf_counter()
    args.output.mkdir(parents=True)
    try:
        processing = processor()
        model = load_model(MODEL, "mps").train()
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=RECIPE["learning_rate"],
            betas=tuple(RECIPE["betas"]),
            eps=RECIPE["epsilon"],
            weight_decay=RECIPE["weight_decay"],
        )
        rows = json.loads(Path(frozen["data"]).read_text())["panels"]["train"]
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
                loss_sum, norm = training_step(
                    model, optimizer, processing, rows, group
                )
                memory(report)
                report["steps"].append(
                    {
                        "epoch": epoch,
                        "indices": [i for batch in group for i in batch],
                        "loss": loss_sum,
                        "gradient_norm": norm,
                        "seconds": time.perf_counter() - tick,
                    }
                )
                if len(report["steps"]) % 10 == 0:
                    print(
                        json.dumps(
                            {
                                "step": len(report["steps"]),
                                "loss": loss_sum,
                                "elapsed": time.perf_counter() - started,
                                "driver": torch.mps.driver_allocated_memory(),
                            }
                        ),
                        flush=True,
                    )
                if time.perf_counter() - started > RECIPE["maximum_seconds"]:
                    raise RuntimeError("Fixed20minute training wall budget exceeded")
                if (
                    args.mode == "preflight"
                    and len(report["steps"]) == RECIPE["preflight_steps"]
                ):
                    report["complete"] = True
                    return
        model.save_pretrained(args.output / "checkpoint", safe_serialization=True)
        report["checkpoint_files"] = {
            str(path): digest(path) for path in (args.output / "checkpoint").iterdir()
        }
        report["complete"] = True
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "report.json", report)
        print(
            json.dumps({key: value for key, value in report.items() if key != "steps"}),
            flush=True,
        )


def inference_checkpoint(args, report):
    model_path = MODEL
    if args.trained is not None:
        training = json.loads((args.trained / "report.json").read_text())
        if (
            not training["complete"]
            or training["mode"] != "train"
            or training["protocol_sha256"] != digest(args.protocol)
        ):
            raise ValueError("Require complete final fixed two-epoch checkpoint")
        for name, value in training["checkpoint_files"].items():
            if digest(Path(name)) != value:
                raise ValueError("Trained checkpoint changed")
        model_path = args.trained / "checkpoint"
        report["training_report_sha256"] = digest(args.trained / "report.json")
    return model_path


def infer(args):
    frozen = checked(args.protocol)
    torch.set_num_threads(2)
    if not torch.backends.mps.is_available():
        raise RuntimeError("Require actual MPS inference")
    report = new_report(args)
    report["rows"] = []
    started = time.perf_counter()
    try:
        model_path = inference_checkpoint(args, report)
        report["model_files"] = {
            str(path): digest(path) for path in model_path.iterdir() if path.is_file()
        }
        processing = processor()
        model = load_model(model_path, "mps").eval()
        data = json.loads(Path(frozen["data"]).read_text())
        for panel in ("oracle", "detected"):
            rows = data["panels"][panel]
            for start in range(0, len(rows), RECIPE["batch"]):
                chosen = rows[start : start + RECIPE["batch"]]
                tick = time.perf_counter()
                with torch.inference_mode():
                    outputs = model.generate(
                        pixels(processing, chosen).to("mps"),
                        max_new_tokens=RECIPE["max_new_tokens"],
                        num_beams=1,
                        do_sample=False,
                        return_dict_in_generate=True,
                        output_scores=True,
                        use_cache=True,
                    )
                    scores = model.compute_transition_scores(
                        outputs.sequences, outputs.scores, normalize_logits=True
                    ).cpu()
                texts = processing.batch_decode(
                    outputs.sequences,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
                if not torch.isfinite(scores).all():
                    raise RuntimeError("Nonfinite generated token scores")
                memory(report)
                elapsed = time.perf_counter() - tick
                for row, text, score, tokens in zip(
                    chosen,
                    texts,
                    scores.tolist(),
                    outputs.sequences.cpu().tolist(),
                    strict=True,
                ):
                    report["rows"].append(
                        {
                            "panel": panel,
                            "id": row["id"],
                            "index": row["index"],
                            "polygon": row["polygon"],
                            "crop_sha256": row["sha256"],
                            "text": text,
                            "token_log_probabilities": score,
                            "tokens": tokens,
                            "batch_seconds": elapsed,
                        }
                    )
                del outputs, scores
        report["complete"] = len(report["rows"]) == 275
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output, report)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key not in ("rows", "steps", "model_files")
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "preflight", "train", "infer"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trained", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Use a new output path; preserve all frozen results")
    if args.mode == "freeze":
        freeze(args)
    elif args.mode == "infer":
        infer(args)
    else:
        train(args)
