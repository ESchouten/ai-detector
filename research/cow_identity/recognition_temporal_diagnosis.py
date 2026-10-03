"""Fixed-score loss stages after the completed early pilot; no new selection."""

import json
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from recognition_temporal_head import ResidualMetricHead, inputs, transform
from safetensors.torch import load_file

ROOT = Path(__file__).parent
FREEZE = ROOT / "recognition_temporal_head_protocol.json"
RUN = Path(".cache/cow-temporal-head-v1")
OUTPUT = ROOT / "results/2026-10-03/recognition/temporal-projection-pilot.json"


def stages(manifest, values, gallery, owners, completed):
    decisions = {
        (frame["second"], d["track"]): d
        for frame in completed["timeline"]
        for d in frame["decisions"]
    }
    selected = [
        i
        for i, row in enumerate(manifest["rows"])
        if row["kind"] == "observation" and 450 <= row["second"] <= 629
    ]
    similarity = values[selected] @ values[gallery].T
    per_cow = np.stack(
        [similarity[:, owners == cow].max(axis=1) for cow in range(1, 7)], axis=1
    )
    order = np.argsort(-per_cow, axis=1, kind="stable")
    index = np.arange(len(selected))
    best, margin = (
        per_cow[index, order[:, 0]],
        per_cow[index, order[:, 0]] - per_cow[index, order[:, 1]],
    )
    counts, records = Counter(), []
    for j, i in enumerate(selected):
        row = manifest["rows"][i]
        observed = decisions[(row["second"], row["track_id"])]
        correct = observed["truth"] == int(order[j, 0]) + 1
        eligible = observed["eligible"]
        accepted = eligible and best[j] >= 0.65 and margin[j] >= 0.1
        counts["all_predicted_crops"] += 1
        counts["raw_rank1_correct_matched_known"] += int(correct)
        counts["geometry_eligible_rank1_correct"] += int(correct and eligible)
        counts["similarity_pass_rank1_correct"] += int(
            correct and eligible and best[j] >= 0.65
        )
        counts["similarity_and_margin_pass_correct"] += int(correct and accepted)
        counts["similarity_and_margin_pass_wrong_or_unmatched"] += int(
            not correct and accepted
        )
        records.append(
            {
                "second": row["second"],
                "track": row["track_id"],
                "truth_for_diagnosis_only": observed["truth"],
                "rank1": int(order[j, 0]) + 1,
                "similarity": float(best[j]),
                "margin": float(margin[j]),
                "eligible": eligible,
                "final_name": observed["name"],
            }
        )
    by_cow = {}
    for cow in range(1, 7):
        rows = [r for r in records if r["truth_for_diagnosis_only"] == cow]
        by_cow[str(cow)] = {
            "matched_observations": len(rows),
            "rank1_correct": sum(r["rank1"] == cow for r in rows),
            "median_max_similarity": float(np.median([r["similarity"] for r in rows])),
            "median_distinct_margin": float(np.median([r["margin"] for r in rows])),
        }
    return {
        "counts": dict(counts),
        "per_cow": by_cow,
        "interpretation": "Per-crop upper bounds before collision rejection and three-sample agreement, at exactly frozen.65/.10; rawrank1 has no abstention and is not naming precision. Original strict finalcounts remain authoritative.",
    }


def main():
    if OUTPUT.exists():
        raise FileExistsError("Preserve completed diagnosis")
    torch.set_num_threads(2)
    freeze, _, manifest, vectors = inputs(FREEZE)
    completed = json.loads((RUN / "calibration.json").read_text())
    training = json.loads((RUN / "training.json").read_text())
    if completed["freeze_sha256"] != digest(FREEZE) or training[
        "checkpoint_sha256"
    ] != digest(RUN / "head-20.safetensors"):
        raise ValueError("Completed result or model changed")
    head = ResidualMetricHead()
    head.load_state_dict(load_file(str(RUN / "head-20.safetensors")), strict=True)
    reviewed = [i for i, r in enumerate(manifest["rows"]) if r["kind"] == "gallery"]
    bank = freeze["dense_bank"]["indices"]
    variants = {
        "baseline": (
            vectors,
            reviewed,
            np.array([manifest["rows"][i]["cow"] for i in reviewed]),
        ),
        "residual20": (
            transform(head, vectors),
            reviewed,
            np.array([manifest["rows"][i]["cow"] for i in reviewed]),
        ),
        "untrained_dense_bank": (
            vectors,
            bank,
            np.array([manifest["rows"][i]["track_id"] + 1 for i in bank]),
        ),
    }
    panels = {}
    for name, (values, gallery, owners) in variants.items():
        result = completed["panels"][name]
        panels[name] = {
            key: value for key, value in result.items() if key != "timeline"
        }
        panels[name]["score_stages"] = stages(manifest, values, gallery, owners, result)
    files = [
        Path(__file__),
        FREEZE,
        RUN / "training.json",
        RUN / "calibration.json",
        RUN / "head-20.safetensors",
        Path(freeze["features"]) / "manifest.json",
        Path(freeze["features"]) / "vectors.npz",
    ]
    write_json(
        OUTPUT,
        {
            "status": "COMPLETE_NEGATIVE_NO_PROMOTION",
            "files": {str(p): digest(p) for p in files},
            "panels": panels,
            "selected": completed["selected"],
            "training": {
                key: value
                for key, value in training.items()
                if key != "training_source_indices"
            },
            "descriptor_runtime": {
                key: manifest[key]
                for key in (
                    "elapsed_seconds",
                    "new_encoded_images",
                    "new_encoder_batches",
                    "mps_driver_peak",
                )
            },
            "limits": completed["limits"],
            "no_further_run": "No later-query or finalwindow inference, no threshold/epoch search, no all-six refit; unknown7/8 excluded from optimization. Densebank is pseudo-lineage-derived, not96human-confirmedphotos.",
        },
    )
    print(json.dumps({name: panel["score_stages"] for name, panel in panels.items()}))


if __name__ == "__main__":
    main()
