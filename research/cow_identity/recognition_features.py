"""Cache annotated public-video crops for recognition-only development.

Final windows are deliberately absent. Publisher identity/boxes are an oracle
diagnostic: this script does not claim detector or tracker performance.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "detector" / "src"))

from benchmark import digest, write_json

PANELS = {
    "enrollment": list(range(0, 300, 5)),
    "development": list(range(330, 630)),
    "development_later": list(range(930, 1230)),
    "calibration": list(range(1230, 1530)),
}


def adapted_fingerprint(base_fingerprint, weights):
    return hashlib.sha256(
        json.dumps(
            {"base": base_fingerprint, "adapted_weights_sha256": digest(weights)},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def crop_quality(box, others, width, height):
    x1, y1, x2, y2 = box
    area = (x2 - x1) * (y2 - y1)
    overlap = 0.0
    for other in others:
        if other is box:
            continue
        a, b, c, d = other
        intersection = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
        overlap = max(overlap, intersection / min(area, (c - a) * (d - b)))
    return {
        "overlap": overlap,
        "minimum_side": min(x2 - x1, y2 - y1),
        "clipped": x1 < 1 or y1 < 1 or x2 >= width - 1 or y2 >= height - 1,
    }


def make_encoder(args):
    from smoke_runtime import CountedEncoder

    from aidetector.adapters.inference.miewid import MiewidEncoder

    if args.encoder in ("megab", "megab-stretch"):
        from recognition_mega import MegaBEncoder

        base_encoder = MegaBEncoder(
            args.weights,
            args.device,
            preprocessing="notebook" if args.encoder == "megab-stretch" else "config",
        )
    else:
        base_encoder = MiewidEncoder(
            args.cache / "models", device=args.device, weights=args.weights
        )
    if args.adapted_weights:
        from safetensors.torch import load_file

        if args.encoder != "miewid":
            raise ValueError(
                "Adapted checkpoints currently use the MIEWid architecture"
            )
        base_encoder.model.load_state_dict(
            load_file(str(args.adapted_weights)), strict=True
        )
        base_encoder.fingerprint = adapted_fingerprint(
            base_encoder.fingerprint, args.adapted_weights
        )
    return CountedEncoder(base_encoder)


def collect(args):
    from video_assessment import annotations, pixels_hash, read_frame, truth_at

    from aidetector.adapters.inference.identity import EmbeddingCache

    records, metadata = annotations(args)
    encoder = make_encoder(args)
    panels = {
        panel: [
            second
            for second in PANELS[panel]
            if panel == "enrollment" or second % args.query_stride == 0
        ]
        for panel in args.panels
    }
    contract = {
        "version": 1,
        "video_sha256": digest(args.video),
        "annotations_sha256": digest(args.annotations),
        "source_sha256": metadata["source_sha256"],
        "encoder_fingerprint": encoder.fingerprint,
        "panels": panels,
        "enrolled_ids": list(range(1, 7)),
        "unknown_ids": [7, 8],
        "crop": "Publisher normalized center-width-height; integer clipped XYXY; BGR",
        "scope": "Oracle boxes/IDs, recognition diagnostic only; no final-test frames",
    }
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous["contract"] == contract:
            if digest(output / "vectors.npz") != previous["vectors_sha256"]:
                raise ValueError("Recorded feature cache changed")
            print(json.dumps({"reused": True, "rows": len(previous["rows"])}))
            return
        raise ValueError("Output contract changed: use a new output directory")
    capture = cv2.VideoCapture(str(args.video))
    cache = EmbeddingCache(args.cache / "queries.sqlite")
    fps = capture.get(cv2.CAP_PROP_FPS)
    rows, vectors = [], []
    started = time.perf_counter()
    try:
        for panel in args.panels:
            for second in panels[panel]:
                frame, image = read_frame(capture, second, fps)
                height, width = image.shape[:2]
                truth = truth_at(records, frame, width, height)
                boxes = [item["box"] for item in truth]
                crops = []
                for item in truth:
                    cow, box = item["cow"], item["box"]
                    if panel == "enrollment" and cow not in range(1, 7):
                        continue
                    x1, y1, x2, y2 = box
                    crop = image[y1:y2, x1:x2].copy()
                    rows.append(
                        {
                            "panel": panel,
                            "second": second,
                            "frame": frame,
                            "cow": cow,
                            "box": box,
                            "pixels_sha256": pixels_hash(crop),
                            **crop_quality(box, boxes, width, height),
                        }
                    )
                    crops.append(crop)
                if crops:
                    vectors.extend(cache.encode(encoder, crops))
            print(json.dumps({"panel": panel, "rows": len(rows)}), flush=True)
    finally:
        capture.release()
        cache.close()
    np.savez_compressed(output / "vectors.npz", vectors=np.asarray(vectors))
    write_json(
        manifest_path,
        {
            "contract": contract,
            "rows": rows,
            "vectors_sha256": digest(output / "vectors.npz"),
            "new_encoded_images": encoder.images,
            "new_encoder_batches": encoder.calls,
            "seconds": time.perf_counter() - started,
        },
    )
    print(json.dumps({"rows": len(rows), "new_encoded_images": encoder.images}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--source-pickle", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--adapted-weights", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cache", type=Path, default=Path(".cache/cow-video-policy-cache")
    )
    parser.add_argument("--device", default="mps")
    parser.add_argument(
        "--encoder", choices=("miewid", "megab", "megab-stretch"), default="miewid"
    )
    parser.add_argument("--query-stride", type=int, default=1)
    parser.add_argument("--panels", choices=PANELS, nargs="+", default=list(PANELS))
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
