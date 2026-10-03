"""Early-only cache/diversity inventory; no learning, query scoring or inference."""

import json
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_masked_pilot import eligible
from scoring import normalize

ROOT = Path(__file__).parent
FEATURES = Path(".cache/cow-cutie/miew-foreground")
GALLERY = Path(".cache/cow-masked-reviewed-gallery-v1")
TEACHER = Path(".cache/cow-cutie/crowded-joint-extended/streaming.json")
OUTPUT = ROOT / "results/2026-10-03/recognition/temporal-training-inventory.json"


def read_features(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if digest(directory / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Feature archive changed")
    with np.load(directory / "vectors.npz", allow_pickle=False) as archive:
        vectors = normalize(archive["vectors"])
    if len(vectors) != len(manifest["rows"]):
        raise ValueError("Feature row alignment changed")
    return manifest, vectors


def quantiles(values):
    return np.quantile(values, [0.1, 0.5, 0.9]).tolist() if len(values) else None


def diversity(rows, vectors, references):
    seconds = np.array([row["second"] for row in rows])
    similarity = np.clip(vectors @ vectors.T, -1, 1)
    gaps = seconds[:, None] - seconds[None, :]
    upper = np.triu(np.ones_like(similarity, dtype=bool), k=1)
    nearest = (vectors @ references.T).max(axis=1)
    temporal_bins = sorted({int(second // 30) for second in seconds})
    return {
        "rows": len(rows),
        "unique_pixel_hashes": len({row["pixels_sha256"] for row in rows}),
        "range_seconds": [int(seconds.min()), int(seconds.max())],
        "occupied_30_second_bins": temporal_bins,
        "consecutive_1s_cosine_p10_median_p90": quantiles(
            similarity[np.abs(gaps) == 1]
        ),
        "same_slot_30_to_120s_cosine_p10_median_p90": quantiles(
            similarity[upper & (np.abs(gaps) >= 30) & (np.abs(gaps) <= 120)]
        ),
        "nearest_same_cow_reviewed_reference_cosine_p10_median_p90": quantiles(nearest),
        "reference_novelty_count_max_cosine_below_0_9": int((nearest < 0.9).sum()),
        "novelty_limit": "Descriptor novelty is not certified different coat view or biological identity; no clustering or training selection is performed.",
    }


def candidate_inventory(timeline):
    counts, runs, previous, lengths = Counter(), {}, {}, Counter()
    simultaneous = []
    for frame in timeline:
        if not 0 <= frame["second"] <= 629:
            continue
        stats = {row["track_id"]: row for row in frame["objects"]}
        accepted = [
            box["track_id"] for box in frame["boxes"] if eligible(frame, box, stats)
        ]
        simultaneous.append(len(accepted))
        for track in accepted:
            counts[track + 1] += 1
            if previous.get(track) != frame["second"] - 1:
                if lengths[track]:
                    runs.setdefault(track + 1, []).append(lengths[track])
                lengths[track] = 0
            lengths[track] += 1
            previous[track] = frame["second"]
    for track, length in lengths.items():
        runs.setdefault(track + 1, []).append(length)
    return {
        "quality": "Existing reviewed-photo selector: p10>=.7, no quarantine, unique recorded reciprocal confirmation, unclipped>=64px; no embeddings/truth for selection.",
        "counts_by_original_named_slot": dict(counts),
        "consecutive_quality_run_lengths_by_original_named_slot": runs,
        "frames_with_at_least_two_eligible_named_slots": sum(
            n >= 2 for n in simultaneous
        ),
        "limits": "Slot continuity is a proposed noisy teacher label, not certified biology; same-frame distinct slots can still describe parts of one animal.",
    }


def execute():
    if OUTPUT.exists():
        raise FileExistsError("Preserve completed early inventory")
    features, vectors = read_features(FEATURES)
    gallery, references = read_features(GALLERY)
    if (
        features["contract"]["encoder_fingerprint"]
        != gallery["contract"]["encoder_fingerprint"]
    ):
        raise ValueError("Different base encoders")
    # Do not compute with any later query vector, even though its cached archive exists.
    indexes = [i for i, row in enumerate(features["rows"]) if 0 <= row["second"] <= 629]
    rows, vectors = [features["rows"][i] for i in indexes], vectors[indexes]
    teacher = json.loads(TEACHER.read_text())
    early = [row for row in teacher["timeline"] if 0 <= row["second"] <= 629]
    if [row["second"] for row in early] != list(range(630)):
        raise ValueError("Preserve complete early source range")
    by_second = {row["second"]: row for row in early}
    statistics = {}
    for cow in range(1, 7):
        selected = [
            i
            for i, row in enumerate(rows)
            if row["track_id"] + 1 == cow
            and row["p10_probability"] >= 0.7
            and min(row["box"][2] - row["box"][0], row["box"][3] - row["box"][1]) >= 64
            and row["box"][0] >= 1
            and row["box"][1] >= 1
            and row["box"][2] < 799
            and row["box"][3] < 599
        ]
        positions = [i for i, row in enumerate(gallery["rows"]) if row["cow"] == cow]
        statistics[str(cow)] = diversity(
            [rows[i] for i in selected], vectors[selected], references[positions]
        )
    files = [Path(__file__), ROOT / "recognition_masked_pilot.py", TEACHER]
    for directory in (FEATURES, GALLERY):
        files.extend((directory / "manifest.json", directory / "vectors.npz"))
    report = {
        "scope": "Assessment only: no training, no query-vector use after629, no pixels/models or threshold selection.",
        "files": {str(path): digest(path) for path in files},
        "encoder_fingerprint": features["contract"]["encoder_fingerprint"],
        "dense_cache": {
            "rows": len(rows),
            "seconds": [min(r["second"] for r in rows), max(r["second"] for r in rows)],
            "source": "Older publisher-box-seeded Cutie propagation, not current joint teacher",
            "exact_full_mask_matches_to_joint": sum(
                row["mask_sha256"] == by_second[row["second"]]["mask_sha256"]
                for row in rows
            ),
            "comparison_unit": "Each cached object row points to full frame-mask hash; mismatch does not prove every object crop differs, but prevents silent provenance substitution.",
        },
        "old_cached_p10_geometry_only_diversity": statistics,
        "current_joint_teacher_early_candidates": candidate_inventory(early),
        "reviewed_gallery": {
            "references": len(gallery["rows"]),
            "per_cow": dict(Counter(row["cow"] for row in gallery["rows"])),
            "seconds": sorted({row["second"] for row in gallery["rows"]}),
        },
        "limitations": [
            "Dense cached candidates lack a matched no-quarantine/reciprocal teacher filter; they are only a representation inventory.",
            "Both packages use one camera/cohort; unknown7/8 must remain excluded from any positive, negative or classifier training if described as withheld identities.",
            "The source arrays are loaded once but later query vectors are sliced out before all dot products.",
        ],
    }
    write_json(OUTPUT, report)
    print(
        json.dumps(
            {
                "dense_cache": report["dense_cache"],
                "diversity": statistics,
                "joint_counts": report["current_joint_teacher_early_candidates"][
                    "counts_by_original_named_slot"
                ],
            }
        )
    )


if __name__ == "__main__":
    execute()
