"""Inspect publisher box dynamics on exposed time only; never rescore predictions."""

import json
from pathlib import Path

import numpy as np
from annotation_audit import publisher_arrays
from benchmark import digest, write_json

ROOT = Path(__file__).parent
PUBLISHER = Path("datasets/8-calves/video/pmfeed_4_3_16.pkl")
SELECTION = ROOT / "results/2026-10-03/detection/extended-error-selection.json"
OUTPUT = ROOT / "results/2026-10-03/detection/annotation-temporal-geometry.json"
COORDINATES = ("x_center", "y_center", "width", "height")


def longest_true_run(values):
    padded = np.concatenate(([False], values, [False])).astype(np.int8)
    changes = np.flatnonzero(np.diff(padded))
    return int((changes[1::2] - changes[::2]).max(initial=0))


def summarize(frames, values):
    """Pixel-coordinate dynamics; 0.001px tolerance is numerical, not a metric gate."""
    differences = np.diff(values, axis=0)
    adjacent = np.diff(frames) == 1
    triples = adjacent[:-1] & adjacent[1:]
    constant_box = adjacent & (np.abs(differences).max(axis=1) <= 0.001)
    linear_box = triples & (np.abs(np.diff(differences, axis=0)).max(axis=1) <= 0.001)
    return {
        "rows": len(frames),
        "consecutive_frame_pairs": int(adjacent.sum()),
        "consecutive_frame_triples": int(triples.sum()),
        "constant_xywh_pairs_0_001px": int(constant_box.sum()),
        "max_constant_xywh_run_frames": longest_true_run(constant_box) + 1,
        "linear_xywh_triples_0_001px": int(linear_box.sum()),
        "max_linear_xywh_run_frames": longest_true_run(linear_box) + 2,
        "per_coordinate": {
            key: {
                "unique_values": int(len(np.unique(values[:, index]))),
                "range_px": [
                    float(values[:, index].min()),
                    float(values[:, index].max()),
                ],
                "constant_consecutive_pairs_0_001px": int(
                    (adjacent & (np.abs(differences[:, index]) <= 0.001)).sum()
                ),
                "absolute_step_px_quantiles_50_95_99": np.quantile(
                    np.abs(differences[adjacent, index]), [0.5, 0.95, 0.99]
                ).tolist(),
            }
            for index, key in enumerate(COORDINATES)
        },
    }


def execute():
    if OUTPUT.exists():
        raise ValueError("Preserve completed annotation diagnosis")
    original = publisher_arrays(PUBLISHER)  # Parses numeric buffers, never unpickles.
    exposed = (original["frame_id"] >= 1) & (original["frame_id"] <= 59981)
    records = {key: value[exposed] for key, value in original.items()}
    selection = json.loads(SELECTION.read_text())
    summaries, local = {}, []
    for cow in range(1, 9):
        selected = records["cow_id"] == cow
        order = np.argsort(records["frame_id"][selected], kind="stable")
        frames = records["frame_id"][selected][order]
        values = np.column_stack([records[key][selected][order] for key in COORDINATES])
        values *= (800, 600, 800, 600)
        summaries[str(cow)] = summarize(frames, values)
        for row in selection["rows"]:
            if row["named_cow"] != cow:
                continue
            central = row["publisher_frame"]
            nearby = np.abs(frames - central) <= 20
            local.append(
                {
                    "selection_index": row["index"],
                    "cow": cow,
                    "second": row["second"],
                    "publisher_frame": central,
                    "central_label_present": bool((frames == central).any()),
                    "statistics": summarize(frames[nearby], values[nearby]),
                    "rows": [
                        {"frame_id": int(frame), "xywh_pixels": value.tolist()}
                        for frame, value in zip(
                            frames[nearby], values[nearby], strict=True
                        )
                    ],
                }
            )
    report = {
        "scope": "Publisher numeric annotations only, exposed source seconds 0..2999 inclusive. No video decode, model, offset search, score change or corrected labels.",
        "files": {
            str(path): digest(path) for path in (Path(__file__), PUBLISHER, SELECTION)
        },
        "coordinate_contract": "Original float64 normalized center x/y/width/height, scaled by native 800x600; one-based publisher frame = 20*seconds+1. Per-cow consecutive frames only.",
        "diagnostic_tolerance_px": 0.001,
        "interpretation_limit": "Short near-linear runs can be tracker smoothing or motion; this diagnostic cannot prove the unpublished annotation implementation. Variable sizes rule out globally fixed rectangles, not occasional manual interpolation.",
        "per_cow": summaries,
        "all_34_error_neighborhoods": sorted(
            local, key=lambda row: row["selection_index"]
        ),
    }
    write_json(OUTPUT, report)
    print(json.dumps(summaries))


if __name__ == "__main__":
    execute()
