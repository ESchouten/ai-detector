"""Fixed evaluation of the final corrected CPU reader; previous outputs stay intact."""

import argparse
import importlib.metadata
import json
import math
import random
import time
from pathlib import Path

from benchmark import digest, write_json
from eartag_ocr import DATA_MANIFEST, score_image, totals
from eartag_trocr_score import character_counts, validate_rows

ROOT = Path(__file__).parent
TRAINING_PROTOCOL = ROOT / "eartag_trocr_cpu_protocol.json"
TRAINING = Path(".cache/cow-ear-tags/trocr-cpu-training")
ORIGINAL = ROOT / "results/2026-10-03/ear-tags/trocr-original-raw.json"


def validate_training(report, protocol_sha256, count, recipe):
    """Only the complete final fresh CPU run is eligible, never the timing pilot."""
    expected = []
    size = recipe["batch"] * recipe["accumulation"]
    for epoch in range(recipe["epochs"]):
        order = list(range(count))
        random.Random(recipe["seed"] + epoch).shuffle(order)
        expected.extend(
            (epoch, order[start : start + size]) for start in range(0, count, size)
        )
    actual = [(row["epoch"], row["indices"]) for row in report["steps"]]
    if (
        not report["complete"]
        or report["error"] is not None
        or report["mode"] != "train"
        or report["actual_device"] != "cpu"
        or report["precision"] != "float32"
        or report["threads"] != 2
        or report["protocol_sha256"] != protocol_sha256
        or actual != expected
        or not report.get("checkpoint_files")
        or any(
            not math.isfinite(row[key])
            for row in report["steps"]
            for key in ("loss", "gradient_norm")
        )
    ):
        raise ValueError("Require the complete finite final corrected CPU recipe")


def freeze(args):
    from eartag_trocr_cpu import validate

    training = validate(TRAINING_PROTOCOL)
    data_protocol = json.loads((ROOT / "eartag_trocr_data_protocol.json").read_text())
    expected_truth = data_protocol["files"][str(DATA_MANIFEST)]
    if digest(DATA_MANIFEST) != expected_truth:
        raise ValueError("Original truth manifest changed")
    paths = [
        Path(__file__),
        ROOT / "test_eartag_trocr_cpu_evaluation.py",
        TRAINING_PROTOCOL,
        DATA_MANIFEST,
        ORIGINAL,
    ]
    write_json(
        args.protocol,
        {
            "scope": "Final corrected CPU-trained reader on the unchanged 275 development crops. Reuse original unadapted reader outputs; no new threshold, model selection or calibration/reserved access. Oracle geometry is conditional localization. All original misses/extras remain in detected-line scoring.",
            "files": {**training["files"], **{str(p): digest(p) for p in paths}},
            "training_protocol_sha256": digest(TRAINING_PROTOCOL),
            "training_directory": str(TRAINING),
            "recipe": training["recipe"],
            "inference_libraries": training["libraries"],
            "score_libraries": training["score_libraries"],
            "data": training["data"],
            "original": str(ORIGINAL),
            "original_protocol_sha256": training["base_protocol_sha256"],
            "generation": "Same pinned processor and FP32 MPS model; batch 4, greedy one beam, max 32 new tokens, use_cache=True. No sampling, text correction, allowlist or confidence threshold. Save literal raw text and token evidence without treating it as calibrated confidence.",
            "truth_sha256": expected_truth,
            "checkpoint_selection": "Only the one final CPU checkpoint after exact two-epoch ordering, 812 steps and 6486 examples. Complete report and checkpoint hashes verified before inference and again before scoring.",
        },
    )


def checked(path, libraries):
    value = json.loads(path.read_text())
    for name, expected in value["files"].items():
        if digest(Path(name)) != expected:
            raise ValueError(f"Frozen evaluation input changed: {name}")
    if digest(DATA_MANIFEST) != value["truth_sha256"]:
        raise ValueError("Frozen truth changed")
    if {name: importlib.metadata.version(name) for name in value[libraries]} != value[
        libraries
    ]:
        raise ValueError("Frozen evaluation libraries changed")
    return value


def final_checkpoint(frozen):
    directory = Path(frozen["training_directory"])
    report_path = directory / "report.json"
    training = json.loads(report_path.read_text())
    data = json.loads(Path(frozen["data"]).read_text())
    validate_training(
        training,
        frozen["training_protocol_sha256"],
        len(data["panels"]["train"]),
        frozen["recipe"],
    )
    for name, expected in training["checkpoint_files"].items():
        if (
            Path(name).parent != directory / "checkpoint"
            or digest(Path(name)) != expected
        ):
            raise ValueError("Final CPU checkpoint changed")
    return directory / "checkpoint", report_path, training, data


def generate_rows(model, processing, data, report):
    import torch
    from eartag_trocr import RECIPE, memory, pixels

    for panel in ("oracle", "detected"):
        rows = data["panels"][panel]
        for start in range(0, len(rows), RECIPE["batch"]):
            selected = rows[start : start + RECIPE["batch"]]
            tick = time.perf_counter()
            with torch.inference_mode():
                output = model.generate(
                    pixels(processing, selected).to("mps"),
                    max_new_tokens=RECIPE["max_new_tokens"],
                    num_beams=1,
                    do_sample=False,
                    return_dict_in_generate=True,
                    output_scores=True,
                    use_cache=True,
                )
                scores = model.compute_transition_scores(
                    output.sequences, output.scores, normalize_logits=True
                ).cpu()
            texts = processing.batch_decode(
                output.sequences,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            if not torch.isfinite(scores).all():
                raise RuntimeError("Nonfinite generated token evidence")
            memory(report)
            seconds = time.perf_counter() - tick
            for row, text, score, tokens in zip(
                selected,
                texts,
                scores.tolist(),
                output.sequences.cpu().tolist(),
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
                        "batch_seconds": seconds,
                    }
                )


def infer(args):
    import torch
    from eartag_trocr import load_model, new_report, processor

    frozen = checked(args.protocol, "inference_libraries")
    if not torch.backends.mps.is_available():
        raise RuntimeError("Require actual MPS inference")
    torch.set_num_threads(2)
    model_path, training_path, training, data = final_checkpoint(frozen)
    report = new_report(args)
    report.update(
        rows=[],
        training_report_sha256=digest(training_path),
        training_protocol_sha256=frozen["training_protocol_sha256"],
        model_files=training["checkpoint_files"],
    )
    started = time.perf_counter()
    try:
        model = load_model(model_path, "mps").eval()
        generate_rows(model, processor(), data, report)
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
                    k: v
                    for k, v in report.items()
                    if k not in ("rows", "steps", "model_files")
                }
            )
        )


def condition(raw, panel, images, truth):
    rows = []
    for key in images:
        predictions = [
            {"polygon": row["polygon"], "text": row["text"], "score": None}
            for row in raw["rows"]
            if row["panel"] == panel and row["id"] == key
        ]
        result = score_image(truth[key], predictions)
        rows.append(
            {"id": key, **result, **character_counts(truth[key], predictions, result)}
        )
    chars = sum(row["truth_characters"] for row in rows)
    errors = sum(row["character_errors_including_misses_extras"] for row in rows)
    return {
        "totals": {
            **totals(rows),
            "character_errors": errors,
            "truth_characters": chars,
            "character_error_rate": errors / chars,
        },
        "rows": rows,
    }


def score(args):
    frozen = checked(args.protocol, "score_libraries")
    _, training_path, training, data = final_checkpoint(frozen)
    original = json.loads(Path(frozen["original"]).read_text())
    adapted = json.loads(args.raw.read_text())
    if (
        original["protocol_sha256"] != frozen["original_protocol_sha256"]
        or adapted["protocol_sha256"] != digest(args.protocol)
        or "training_report_sha256" in original
        or adapted["training_report_sha256"] != digest(training_path)
        or adapted["model_files"] != training["checkpoint_files"]
    ):
        raise ValueError("Require original baseline and exact corrected final reader")
    for raw in (original, adapted):
        validate_rows(raw, data)
    truth = {
        row["id"]: row["lines"] for row in json.loads(DATA_MANIFEST.read_text())["rows"]
    }
    images = list(dict.fromkeys(row["id"] for row in data["panels"]["oracle"]))
    conditions = {
        f"{name}_{panel}": condition(raw, panel, images, truth)
        for name, raw in (("original", original), ("corrected_cpu", adapted))
        for panel in ("oracle", "detected")
    }
    result = {
        "scope": frozen["scope"],
        "protocol_sha256": digest(args.protocol),
        "training_report_sha256": digest(training_path),
        "truth_sha256": digest(DATA_MANIFEST),
        "raw_sha256": {str(p): digest(p) for p in (Path(frozen["original"]), args.raw)},
        "conditions": conditions,
    }
    write_json(args.output, result)
    print(json.dumps({name: value["totals"] for name, value in conditions.items()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "infer", "score"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.protocol if args.mode == "freeze" else args.output
    if target is None or target.exists():
        parser.error("Preserve previous immutable protocols and outputs")
    {"freeze": freeze, "infer": infer, "score": score}[args.mode](args)
