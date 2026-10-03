"""Continuous0–2999 extension using unchanged births, SDK and strict scorer stages."""

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_birth_extended_cache import checked_inputs as checked_cache
from detection_birth_run import execute_frames
from detection_birth_score import verify_frame
from detection_cutie import open_core
from detection_quarantine_recovery import CorroboratedRecovery
from detection_reserved_score import acceptance, pooled_naming, runtime_summary
from detection_sam_tracking import score
from detection_streaming_assessment import THRESHOLDS
from joint_readout_prefix import FIELDS, mask_path
from passage_entry_control import OneHertzQuarantine, runtime_contract
from video_assessment import annotations

WINDOWS = ((1800, 2099), (2700, 2999))
POLICY_FIELDS = (
    "births",
    "naming",
    "recovery",
    "resource_limits",
    "max_internal_size",
    "mem_every",
    "use_long_term",
    "cache_reclaim_bytes",
    "seeded_cows",
    "named_cows",
    "source_commit",
    "libraries",
    "dynamic_additions",
    "deletion",
)
MODEL_INPUTS = (
    "seed_manifest",
    "seed_masks",
    "upstream",
    "cutie_model",
    "sam_model",
    "yolo_model",
    "quarantine_protocol",
)


def unchanged_policy(protocol, baseline):
    if any(protocol[k] != baseline[k] for k in POLICY_FIELDS) or any(
        protocol["inputs"][k] != baseline["inputs"][k] for k in MODEL_INPUTS
    ):
        raise ValueError("The selected method must remain unchanged")
    if (
        protocol["last_processed_second"] != 2999
        or protocol["processing_fps"] != 2
        or protocol["comparison_windows"] != [list(w) for w in WINDOWS]
    ):
        raise ValueError("Only the frozen continuous2999extension is allowed")


def checked_inputs(path):
    protocol = json.loads(path.read_text())
    for filename, expected in protocol["files"].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f"Changed frozen extended input: {filename}")
    baseline = json.loads(Path(protocol["inputs"]["prefix_protocol"]).read_text())
    unchanged_policy(protocol, baseline)
    _, clip, _ = checked_cache(Path(protocol["inputs"]["cache_protocol"]))
    cached = json.loads(Path(protocol["inputs"]["proposals"]).read_text())
    if not cached["complete"] or cached["protocol_sha256"] != digest(
        Path(protocol["inputs"]["cache_protocol"])
    ):
        raise ValueError("Complete frozen extended proposals required")
    for source, row in zip(clip["rows"], cached["timeline"], strict=True):
        if (
            source["second"] != row["second"]
            or source["publisher_frame"] != row["publisher_frame"]
            or source["pixels_sha256"] != row["source_pixels_sha256"]
        ):
            raise ValueError("Extended cached source correspondence changed")
    seeds = json.loads(Path(protocol["inputs"]["seed_manifest"]).read_text())["rows"][0]
    original = json.loads(Path(protocol["inputs"]["prefix_predictions"]).read_text())
    if (
        not original["complete"]
        or seeds["prompts"] != original["provenance"]["seed_prompts"]
    ):
        raise ValueError("The six original reviewed names must remain unchanged")
    return protocol, clip, seeds, cached


def run(args):
    import torch
    from cutie.inference import memory_manager
    from ultralytics import SAM

    protocol, clip, seeds, cached = checked_inputs(args.protocol)
    libraries = runtime_contract(protocol)
    if (
        not Path(memory_manager.__file__)
        .resolve()
        .is_relative_to(Path(protocol["inputs"]["upstream"]).resolve())
    ):
        raise ValueError("Imported SDK is outside the pinned isolated candidate")
    if not torch.backends.mps.is_available():
        raise RuntimeError("Actual MPS required")
    torch.set_num_threads(2)
    (args.output / "masks").mkdir(parents=True, exist_ok=False)
    (args.output / "sam").mkdir()
    value = {
        "complete": False,
        "provenance": {
            "protocol_sha256": digest(args.protocol),
            "libraries": libraries,
            "seed_prompts": seeds["prompts"],
            "detector_cache_sha256": digest(Path(protocol["inputs"]["proposals"])),
            "performance_scope": "Cached detector evidence; propagation plus same-frame SAM is not complete joint live timing",
        },
        "timeline": [],
        "all_frames": [],
        "frame_seconds": [],
        "memory_samples": [],
        "stop_reason": None,
    }
    started = time.perf_counter()
    try:
        core, config = open_core(
            SimpleNamespace(
                upstream=Path(protocol["inputs"]["upstream"]),
                model=Path(protocol["inputs"]["cutie_model"]),
                device="mps",
            ),
            protocol,
        )
        parameter = next(core.network.parameters())
        if parameter.device.type != "mps" or parameter.dtype != torch.float32:
            raise ValueError("Cutie must retain FP32 MPS")
        sam = SAM(protocol["inputs"]["sam_model"])
        rules = json.loads(Path(protocol["inputs"]["quarantine_protocol"]).read_text())
        tracker = OneHertzQuarantine(
            CorroboratedRecovery(rules, range(1, 7), protocol["recovery"])
        )
        value.update(
            config=config,
            model_metadata={
                "cutie_device": str(parameter.device),
                "cutie_dtype": str(parameter.dtype),
                "sam_device": "cpu",
                "detector": cached["model_metadata"],
            },
        )
        value["initialization_seconds"] = time.perf_counter() - started
        execute_frames(args, protocol, clip, value, core, sam, tracker, cached)
        value["quarantine_events"] = tracker.tracker.events
        value["complete"] = (
            len(value["all_frames"]) == 5999
            and len(value["timeline"]) == 3000
            and not value["stop_reason"]
        )
    except BaseException as error:
        value["stop_reason"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        value["elapsed_seconds"] = time.perf_counter() - started
        write_json(args.output / "streaming.json", value)


def full_prefix(before, after, directories):
    """Compare all closed-loop decisions through1529, including post-birth outputs."""
    old = before["all_frames"]
    if (
        not before["complete"]
        or len(old) != 3059
        or len(after["all_frames"]) < len(old)
    ):
        raise ValueError("Require the complete original3059inputprefix")
    errors = []
    for a, b in zip(old, after["all_frames"][: len(old)], strict=True):
        for directory, row in zip(directories, (a, b), strict=True):
            if digest(mask_path(directory, row)) != row["mask_sha256"]:
                raise ValueError("Prefix output bytes changed")
        fields = [k for k in (*FIELDS, "publisher_frame") if a[k] != b[k]]
        # Paths/timings vary, but SAM choices and rejection/acceptance must not.
        if sam_choices(a) != sam_choices(b):
            fields.append("sam_attempt_decisions")
        if fields:
            errors.append({"second": a["second"], "fields": fields})
    old_events = before["quarantine_events"]
    new_events = [e for e in after["quarantine_events"] if e["second"] <= 1529]
    return {
        "input_frames": len(old),
        "differences": errors,
        "quarantine_events_equal": old_events == new_events,
        "exact": not errors and old_events == new_events,
    }


def sam_choices(row):
    return [
        {k: v for k, v in item.items() if k not in ("cache", "batch_seconds")}
        for item in row["sam_attempts"]
    ]


def validate_frames(value, clip, directory):
    if len(value["all_frames"]) != 5999 or len(value["timeline"]) != 3000:
        raise ValueError("Retain all continuous source and scoring timestamps")
    live = set(range(1, 7))
    for index, (frame, source) in enumerate(
        zip(value["all_frames"], clip["rows"], strict=True)
    ):
        verify_frame(frame, source, index, directory, live)
    if [r for r in value["all_frames"] if float(r["second"]).is_integer()] != value[
        "timeline"
    ]:
        raise ValueError("Scored rows must equal real integer decisions")


def assess(args):
    protocol, clip, seeds, cached = checked_inputs(args.protocol)
    value = json.loads(args.streaming.read_text())
    if (
        value["provenance"]["protocol_sha256"] != digest(args.protocol)
        or value["provenance"]["libraries"] != protocol["libraries"]
    ):
        raise ValueError("Different continuous execution provenance")
    if args.output.exists():
        raise FileExistsError("Preserve all prior reports")
    bindings = {
        str(p): digest(p) for p in (args.protocol, args.streaming, Path(__file__))
    }
    if not value["complete"]:
        write_json(
            args.output,
            {
                "status": "FAILED_INCOMPLETE_EXTENSION",
                "stop_reason": value["stop_reason"],
                "processed_frames": len(value["all_frames"]),
                "expected_frames": 5999,
                "sources": bindings,
                "scores": None,
            },
        )
        return
    validate_frames(value, clip, args.streaming.parent)
    prefix_path = Path(protocol["inputs"]["prefix_predictions"])
    prefix = full_prefix(
        json.loads(prefix_path.read_text()),
        value,
        (prefix_path.parent, args.streaming.parent),
    )
    for path in (args.annotations, args.source_pickle):
        if digest(path) != protocol["files"][str(path)]:
            raise ValueError("Original all-eight truth changed")
    records, _ = annotations(args)
    slots = [*seeds["prompts"], {"cow": None}, {"cow": None}]
    panels = {
        str(w[0]): score(
            value,
            records,
            clip,
            {**protocol, "score_seconds": w},
            slots,
            name_allowed=lambda frame, box: box.track_id in frame["named_track_ids"],
        )
        for w in WINDOWS
    }
    batches = {
        a["cache"]: a["batch_seconds"]
        for r in value["all_frames"]
        for a in r["sam_attempts"]
    }
    report = {
        "status": "COMPLETE_EXPOSED_EXTENSION"
        if prefix["exact"]
        else "FAILED_PREFIX_PARITY",
        "sources": bindings,
        "full_development_prefix_parity": prefix,
        "conditions": panels,
        "pooled": pooled_naming(panels),
        "acceptance": {
            key: acceptance(panel, THRESHOLDS) for key, panel in panels.items()
        },
        "births": [
            {"second": row["second"], "stable_id": i, "name": None}
            for row in value["all_frames"]
            for i in row["born_ids"]
        ],
        "sam_batches": len(batches),
        "sam_batch_seconds": sum(batches.values()),
        "sam_prompt_count": sum(len(r["sam_attempts"]) for r in value["all_frames"]),
        "runtime_cached_propagation_plus_sam": runtime_summary(value, 2),
        "extended_detector_fill": {
            "elapsed_seconds": cached["elapsed_seconds"],
            "model_seconds": sum(cached["new_inference_seconds"]),
            "new_calls": len(cached["new_inference_seconds"]),
        },
        "limitation": "Previously exposed1800–2099/2700–2999 regression with unchanged method, full all-eight denominators and continuous state. Cached detector timing is not measured live performance. No biological re-identification, deletion, automatic promotion or new-farm claim;3000+ remains closed.",
    }
    write_json(args.output, report)
    print(
        json.dumps({k: report[k] for k in ("status", "acceptance", "pooled", "births")})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "score"))
    for name in ("protocol", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("streaming", "annotations", "source-pickle"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    (run if args.mode == "run" else assess)(args)
