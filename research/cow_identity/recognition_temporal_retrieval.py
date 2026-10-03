"""Post-hoc score distributions at the fixed completed operating point."""

import json
from pathlib import Path

import numpy as np
import torch
from benchmark import digest, write_json
from recognition_temporal_head import ResidualMetricHead, inputs, transform
from safetensors.torch import load_file

ROOT = Path(__file__).parent
FREEZE = ROOT / "recognition_temporal_head_protocol.json"
RUN = Path(".cache/cow-temporal-head-v1")


def quantiles(values):
    return {
        "n": len(values),
        "p05_median_p95": np.quantile(values, (0.05, 0.5, 0.95)).tolist()
        if len(values)
        else None,
    }


def describe(manifest, vectors, gallery, owners, panel):
    decisions = {
        (f["second"], d["track"]): d for f in panel["timeline"] for d in f["decisions"]
    }
    indices = [
        i
        for i, r in enumerate(manifest["rows"])
        if r["kind"] == "observation" and 450 <= r["second"] <= 629
    ]
    matches = vectors[indices] @ vectors[gallery].T
    scores = np.stack(
        [matches[:, owners == cow].max(axis=1) for cow in range(1, 7)], axis=1
    )
    ordered = np.argsort(-scores, axis=1, kind="stable")
    positions = np.arange(len(indices))
    best = scores[positions, ordered[:, 0]]
    margin = best - scores[positions, ordered[:, 1]]
    truth = np.array(
        [
            decisions[(manifest["rows"][i]["second"], manifest["rows"][i]["track_id"])][
                "truth"
            ]
            or 0
            for i in indices
        ]
    )
    predicted = ordered[:, 0] + 1
    eligible = np.array(
        [
            decisions[(manifest["rows"][i]["second"], manifest["rows"][i]["track_id"])][
                "eligible"
            ]
            for i in indices
        ]
    )
    result = {}
    for cow in range(1, 7):
        matched = truth == cow
        correct = matched & (predicted == cow)
        wrong = matched & (predicted != cow)
        result[str(cow)] = {
            "matched": int(matched.sum()),
            "rank1_correct": int(correct.sum()),
            "eligible_correct": int((correct & eligible).sum()),
            "correct_top1_similarity": quantiles(best[correct]),
            "correct_top1_margin": quantiles(margin[correct]),
            "wrong_top1_similarity": quantiles(best[wrong]),
            "true_identity_similarity_all_matched": quantiles(scores[matched, cow - 1]),
        }
    return {
        "per_cow": result,
        "unknown7_8_top1_similarity": quantiles(best[truth >= 7]),
        "unknown7_8_top1_margin": quantiles(margin[truth >= 7]),
        "unmatched_top1_similarity": quantiles(best[truth == 0]),
        "stage_limit": "These are descriptive fixed-model quantiles, not an alternative threshold or rescored trial. Incorrect biological names and unmatched localization errors remain separate in the original report.",
    }


def main():
    output = (
        ROOT / "results/2026-10-03/recognition/temporal-retrieval-distributions.json"
    )
    if output.exists():
        raise FileExistsError("Preserve complete diagnosis")
    torch.set_num_threads(2)
    freeze, _, manifest, vectors = inputs(FREEZE)
    completed = json.loads((RUN / "calibration.json").read_text())
    head = ResidualMetricHead()
    head.load_state_dict(load_file(str(RUN / "head-20.safetensors")), strict=True)
    reviewed = [i for i, r in enumerate(manifest["rows"]) if r["kind"] == "gallery"]
    owners = np.array([manifest["rows"][i]["cow"] for i in reviewed])
    bank = freeze["dense_bank"]["indices"]
    variants = {
        "baseline": (vectors, reviewed, owners),
        "residual20": (transform(head, vectors), reviewed, owners),
        "untrained_dense_bank": (
            vectors,
            bank,
            np.array([manifest["rows"][i]["track_id"] + 1 for i in bank]),
        ),
    }
    panels = {
        name: describe(manifest, values, gallery, identity, completed["panels"][name])
        for name, (values, gallery, identity) in variants.items()
    }
    write_json(
        output,
        {
            "files": {
                str(p): digest(p)
                for p in (
                    Path(__file__),
                    FREEZE,
                    RUN / "calibration.json",
                    RUN / "head-20.safetensors",
                )
            },
            "scope": "All completed450–629 predictions, no new selection/parameter/grid or future observation",
            "panels": panels,
        },
    )
    print(
        json.dumps(
            {
                name: {
                    cow: {
                        "rank1": f"{row['rank1_correct']}/{row['matched']}",
                        "tp_similarity": row["correct_top1_similarity"][
                            "p05_median_p95"
                        ],
                        "tp_margin": row["correct_top1_margin"]["p05_median_p95"],
                    }
                    for cow, row in panel["per_cow"].items()
                }
                for name, panel in panels.items()
            }
        )
    )


if __name__ == "__main__":
    main()
