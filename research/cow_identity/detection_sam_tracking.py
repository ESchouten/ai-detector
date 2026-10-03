"""Measure SDK video propagation from one idealized, manually named seed frame."""

import argparse
import json
import resource
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np
from benchmark import digest, write_json
from detection_tracking import summarize
from video_assessment import (
    VideoMetrics,
    annotations,
    detector_libraries,
    pixels_hash,
    read_frame,
    truth_at,
)

from aidetector.domain.models import BoundingBox, IdentityMatch

PROTOCOL = Path(__file__).with_name("detection_sam_protocol.json")
RESOURCE_LIMITS = {
    "max_mps_driver_bytes": 8 * 1024**3,
    "max_mean_seconds_per_frame": 1.0,
    "warmup_frames": 10,
    "timing_window_frames": 30,
}


def sampled_seconds(protocol):
    rate = protocol["processing_fps"]
    return [
        index / rate for index in range(protocol["last_processed_second"] * rate + 1)
    ]


def visible_ids(visible, object_indices):
    if len(visible) != len(object_indices):
        raise ValueError("SAM object slots do not match mask slots")
    return [object_indices[index] for index, keep in enumerate(visible) if keep]


def verify_clip(path, rows):
    capture = cv2.VideoCapture(str(path))
    try:
        for row in rows:
            ok, image = capture.read()
            if not ok or pixels_hash(image) != row["pixels_sha256"]:
                raise ValueError("Lossless sampled clip differs from source pixels")
        if capture.read()[0]:
            raise ValueError("Sampled clip contains unexpected extra frames")
    finally:
        capture.release()


def write_clip(video, target, protocol):
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(
        str(target),
        cv2.VideoWriter_fourcc(*"FFV1"),
        protocol["processing_fps"],
        (width, height),
    )
    rows = []
    try:
        if not writer.isOpened():
            raise ValueError("OpenCV cannot create the lossless FFV1 research clip")
        for second in sampled_seconds(protocol):
            frame_id, image = read_frame(capture, second, fps)
            writer.write(image)
            rows.append(
                {
                    "second": second,
                    "publisher_frame": frame_id,
                    "pixels_sha256": pixels_hash(image),
                }
            )
    finally:
        capture.release()
        writer.release()
    verify_clip(target, rows)
    return {"rows": rows, "width": width, "height": height, "source_fps": fps}


def prepare(args, protocol):
    args.cache.mkdir(parents=True, exist_ok=True)
    directory = args.sample_cache or args.cache
    directory.mkdir(parents=True, exist_ok=True)
    clip = directory / "sampled.avi"
    path = directory / "sampled.json"
    contract = {
        "video_sha256": digest(args.video),
        "opencv": cv2.__version__,
    }
    if path.exists():
        manifest = json.loads(path.read_text())
        source_contract = {key: manifest["contract"][key] for key in contract}
        if source_contract != contract or digest(clip) != manifest["clip_sha256"]:
            raise ValueError(
                "Existing sampled clip has different provenance; use a fresh cache"
            )
        if [row["second"] for row in manifest["rows"]] != sampled_seconds(protocol):
            raise ValueError("Sampled timestamps differ from the frozen protocol")
        if any(
            row["publisher_frame"] != round(row["second"] * manifest["source_fps"]) + 1
            for row in manifest["rows"]
        ):
            raise ValueError("Sampled source frame indices are inconsistent")
        verify_clip(clip, manifest["rows"])
        return manifest
    manifest = {
        "contract": {**contract, "protocol_sha256": digest(args.protocol)},
        **write_clip(args.video, clip, protocol),
    }
    manifest["clip_sha256"] = digest(clip)
    write_json(path, manifest)
    return manifest


def predictor_for(model, device, protocol):
    from ultralytics.models.sam import SAM2VideoPredictor

    class StableObjectPredictor(SAM2VideoPredictor):
        def postprocess(self, preds, img, orig_imgs):
            outputs = self.inference_state["output_dict"]
            frame = self.dataset.frame
            current = (
                outputs["cond_frame_outputs"][frame]
                if frame in outputs["cond_frame_outputs"]
                else outputs["non_cond_frame_outputs"][frame]
            )
            masks = current["pred_masks"].flatten(0, 1)
            keep = (masks > self.model.mask_threshold).flatten(1).any(1).cpu().tolist()
            self.visible_objects = visible_ids(
                keep, self.inference_state["obj_idx_to_id"]
            )
            return super().postprocess(preds, img, orig_imgs)

    return StableObjectPredictor(
        overrides={
            "model": str(model),
            "task": "segment",
            "mode": "predict",
            "device": device,
            "imgsz": protocol["imgsz"],
            "conf": 0.25,
            "save": False,
            "verbose": False,
            "vid_stride": 1,
            "quantize": 32,
        }
    )


def masked_boxes(result, object_ids):
    masks = [] if result.masks is None else result.masks.data.cpu().numpy()
    boxes = []
    for mask, object_id in zip(masks, object_ids, strict=True):
        ys, xs = np.nonzero(mask)
        if not len(xs) or xs.min() == xs.max() or ys.min() == ys.max():
            continue
        boxes.append(
            asdict(
                BoundingBox(
                    int(xs.min()),
                    int(ys.min()),
                    int(xs.max()),
                    int(ys.max()),
                    "cow",
                    1.0,
                    int(object_id),
                )
            )
        )
    return boxes


def memory_usage(predictor, device):
    import torch

    state = predictor.inference_state
    return {
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "mps_allocated_bytes": torch.mps.current_allocated_memory()
        if device == "mps"
        else 0,
        "mps_driver_bytes": torch.mps.driver_allocated_memory()
        if device == "mps"
        else 0,
        "retained_noncondition_frames": len(
            state["output_dict"]["non_cond_frame_outputs"]
        ),
        "retained_condition_frames": len(state["output_dict"]["cond_frame_outputs"]),
        "tracked_frame_indices": len(state["frames_already_tracked"]),
    }


def save_preview(result, object_ids, seeds, path):
    image = result.orig_img.copy()
    masks = [] if result.masks is None else result.masks.data.cpu().numpy()
    for mask, object_id in zip(masks, object_ids, strict=True):
        ys, xs = np.nonzero(mask)
        if not len(xs):
            continue
        color = np.array(
            [
                50 + object_id * 57 % 205,
                50 + object_id * 91 % 205,
                50 + object_id * 139 % 205,
            ]
        )
        image[mask.astype(bool)] = (
            0.65 * image[mask.astype(bool)] + 0.35 * color
        ).astype(np.uint8)
        cow = seeds[object_id]["cow"]
        label = f"Seed cow {cow}" if cow <= 6 else f"Anonymous slot {object_id}"
        cv2.putText(
            image,
            label,
            (int(xs.min()), max(15, int(ys.min()))),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
        )
    if not cv2.imwrite(str(path), image):
        raise ValueError("Could not save tracking preview")
    return {"file": path.name, "sha256": digest(path)}


def resource_stop(memory, durations, limits):
    if memory["mps_driver_bytes"] > limits["max_mps_driver_bytes"]:
        return "MPS driver allocation exceeded the frozen memory budget"
    window = limits["timing_window_frames"]
    if (
        len(durations) >= limits["warmup_frames"] + window
        and np.mean(durations[-window:]) > limits["max_mean_seconds_per_frame"]
    ):
        return "Sustained inference exceeded the frozen frame-time budget"
    return None


def reclaim_mps_cache(predictor, device, threshold):
    import torch

    before = memory_usage(predictor, device)
    if device != "mps" or threshold is None or before["mps_driver_bytes"] <= threshold:
        return before, None
    started = time.perf_counter()
    torch.mps.synchronize()
    torch.mps.empty_cache()
    torch.mps.synchronize()
    after = memory_usage(predictor, device)
    return after, {
        "before": before,
        "after": after,
        "seconds": time.perf_counter() - started,
    }


def propagate(args, protocol, clip, seeds):
    import torch

    torch.set_num_threads(2)
    predictor = predictor_for(args.model, args.device, protocol)
    rows, memory, previews, durations, reclamations = [], [], [], [], []
    started = time.perf_counter()
    previous = started
    stop_reason = None
    peak_driver_bytes = 0
    limits = protocol.get("resource_limits", RESOURCE_LIMITS)
    results = predictor(
        source=str((args.sample_cache or args.cache) / "sampled.avi"),
        bboxes=[row["box"] for row in seeds],
        stream=True,
    )
    for index, (result, source) in enumerate(zip(results, clip["rows"], strict=True)):
        resources, reclamation = reclaim_mps_cache(
            predictor, args.device, protocol.get("reclaim_after_bytes")
        )
        if reclamation:
            reclamations.append({"second": source["second"], **reclamation})
        durations.append(time.perf_counter() - previous)
        if pixels_hash(result.orig_img) != source["pixels_sha256"]:
            raise ValueError("SDK loader and sampled source timestamps differ")
        if source["second"].is_integer():
            rows.append(
                {
                    "second": int(source["second"]),
                    "boxes": masked_boxes(result, predictor.visible_objects),
                }
            )
        if source["second"] in (0, 330, 629):
            previews.append(
                save_preview(
                    result,
                    predictor.visible_objects,
                    seeds,
                    args.cache / f"preview-{int(source['second'])}.jpg",
                )
            )
        peak_driver_bytes = max(peak_driver_bytes, resources["mps_driver_bytes"])
        stop_reason = resource_stop(resources, durations, limits)
        if index % 50 == 0 or index == len(clip["rows"]) - 1 or stop_reason:
            memory.append({"second": source["second"], **resources})
            print(
                json.dumps(
                    {
                        "processed_frames": index + 1,
                        "elapsed_seconds": time.perf_counter() - started,
                        "mps_driver_bytes": resources["mps_driver_bytes"],
                    }
                ),
                flush=True,
            )
        previous = time.perf_counter()
        if stop_reason:
            results.close()
            break
    return {
        "complete": stop_reason is None,
        "stop_reason": stop_reason,
        "peak_observed_mps_driver_bytes": peak_driver_bytes,
        "frame_seconds": durations,
        "cache_reclamations": reclamations,
        "timeline": rows,
        "memory_samples": memory,
        "elapsed_seconds": time.perf_counter() - started,
        "parameter_dtype": str(next(predictor.model.parameters()).dtype),
        "actual_device": str(next(predictor.model.parameters()).device),
        "previews": previews,
    }


def score(value, records, clip, protocol, seeds, name_allowed=None):
    if [frame["second"] for frame in value["timeline"]] != list(
        range(protocol["last_processed_second"] + 1)
    ):
        raise ValueError(
            "Propagation must contain every frozen integer-second timestamp"
        )
    named = VideoMetrics()
    timeline = []
    for frame in value["timeline"]:
        if (
            not protocol["score_seconds"][0]
            <= frame["second"]
            <= protocol["score_seconds"][1]
        ):
            continue
        truth = truth_at(
            records,
            round(frame["second"] * clip["source_fps"]) + 1,
            clip["width"],
            clip["height"],
        )
        boxes = [BoundingBox(**row) for row in frame["boxes"]]
        for index, box in enumerate(boxes):
            cow = seeds[box.track_id]["cow"]
            if cow in protocol["named_cows"] and (
                name_allowed is None or name_allowed(frame, box)
            ):
                boxes[index] = replace(
                    box,
                    identity=IdentityMatch(
                        identity_id=f"{cow:032x}", name=f"Seed cow {cow}"
                    ),
                )
        named.add(frame["second"], boxes, truth, [True] * len(boxes))
        timeline.append({**frame, "truth": truth})
    counts = dict(named.counts)
    total_named = sum(
        counts[key]
        for key in ("correct_name", "wrong_name", "unknown_named", "unmatched_named")
    )
    return {
        "tracking": summarize({"timeline": timeline}),
        "naming_counts": counts,
        "known_coverage": counts["correct_name"] / counts["visible_known"],
        "conservative_precision": counts["correct_name"] / total_named
        if total_named
        else 0.0,
        "name_confusion": dict(named.names),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    for name in ("video", "annotations", "source-pickle", "model", "cache"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--sample-cache", type=Path)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    for path, key in (
        (args.video, "video_sha256"),
        (args.model, "model_sha256"),
        (args.source_pickle, "source_annotations_sha256"),
    ):
        if digest(path) != protocol[key]:
            parser.error(f"Unexpected source for {key}")
    records, _ = annotations(args)
    clip = prepare(args, protocol)
    seeds = sorted(
        truth_at(records, 1, clip["width"], clip["height"]), key=lambda row: row["cow"]
    )
    if [row["cow"] for row in seeds] != protocol["seeded_cows"]:
        parser.error(
            "Initial frame does not contain exactly the frozen eight seed cows"
        )
    if args.mode == "prepare":
        print(
            json.dumps(
                {
                    "sampled_frames": len(clip["rows"]),
                    "clip_sha256": clip["clip_sha256"],
                }
            )
        )
        return
    provenance = {
        "runner_sha256": digest(Path(__file__)),
        "protocol_sha256": digest(args.protocol),
        "resource_limits": protocol.get("resource_limits", RESOURCE_LIMITS),
        "model_sha256": digest(args.model),
        "clip_sha256": clip["clip_sha256"],
        "sampled_manifest_sha256": digest(
            (args.sample_cache or args.cache) / "sampled.json"
        ),
        "annotations_sha256": digest(args.annotations),
        "libraries": detector_libraries(),
        "device": args.device,
        "seed_prompts": seeds,
    }
    cache = args.cache / "propagation.json"
    if cache.exists():
        value = json.loads(cache.read_text())
        if value["provenance"] != provenance:
            parser.error(
                "Existing propagation has different provenance; use a fresh cache"
            )
    else:
        value = {"provenance": provenance, **propagate(args, protocol, clip, seeds)}
        write_json(cache, value)
    result = {
        "scope": protocol["purpose"],
        "complete": value["complete"],
        "stop_reason": value["stop_reason"],
        "peak_observed_mps_driver_bytes": value["peak_observed_mps_driver_bytes"],
        "provenance": provenance,
        "elapsed_seconds": value["elapsed_seconds"],
        "parameter_dtype": value["parameter_dtype"],
        "actual_device": value["actual_device"],
        "previews": value["previews"],
        "memory_samples": value["memory_samples"],
        "frame_seconds": value["frame_seconds"],
        "cache_reclamations": value["cache_reclamations"],
        "metrics": score(value, records, clip, protocol, seeds)
        if value["complete"]
        else None,
    }
    write_json(args.cache / "report.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
