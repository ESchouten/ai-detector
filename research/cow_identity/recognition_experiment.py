"""Gallery/enrollment ablations on cached, oracle-tracked development crops.

Only early enrollment images fit gallery transforms. Calibration alone selects
thresholds. The reserved final-test windows are not part of these inputs.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from ablation import whitening
from benchmark import digest, write_json
from scoring import Scores, metrics, normalize, score


def select_gallery(rows, vectors, method):
    chosen = []
    for cow in range(1, 7):
        indices = np.array(
            [
                i
                for i, row in enumerate(rows)
                if row["panel"] == "enrollment" and row["cow"] == cow
            ]
        )
        if method == "legacy3":
            selected = [i for i in indices if rows[i]["second"] in (0, 10, 20)]
        elif method == "uniform10":
            selected = indices[
                np.linspace(0, len(indices) - 1, 10).astype(int)
            ].tolist()
        else:
            count = 5 if method == "diverse5" else 10
            # Exclude heavy overlaps if enough unobstructed early examples exist.
            clean = np.array(
                [
                    i
                    for i in indices
                    if rows[i]["overlap"] < 0.3 and not rows[i]["clipped"]
                ]
            )
            if len(clean) >= count:
                indices = clean
            values = vectors[indices]
            similarities = values @ values.T
            selected_local = [int(similarities.mean(axis=1).argmax())]
            for _ in range(min(count, len(indices)) - 1):
                distance = 1 - similarities[:, selected_local].max(axis=1)
                distance[selected_local] = -1
                selected_local.append(int(distance.argmax()))
            selected = indices[selected_local].tolist()
        chosen.extend(selected)
    return np.array(chosen)


def pooled_queries(rows, vectors, count):
    result = []
    recent = {}
    for row, vector in zip(rows, vectors, strict=True):
        key = (row["panel"], row["cow"])
        previous = recent.get(key, [])
        previous = [
            (second, value)
            for second, value in previous
            if 0 < row["second"] - second < count
        ]
        previous.append((row["second"], vector))
        recent[key] = previous
        result.append(np.mean([value for _, value in previous], axis=0))
    return normalize(np.asarray(result))


def calibrate_target(panel):
    correct = panel.known & (panel.predicted == panel.truth)
    best = (0, 1.01, 1.01)
    for threshold in np.arange(0.2, 1.001, 0.01):
        for margin in np.arange(0.0, 0.501, 0.01):
            accepted = (panel.similarity >= threshold) & (panel.margin >= margin)
            named = int(accepted.sum())
            hits = int((accepted & correct).sum())
            false_unknown = int((accepted & ~panel.known).sum())
            if (
                named
                and hits / named >= 0.99
                and false_unknown <= 0.01 * (~panel.known).sum()
            ):
                best = max(best, (hits, float(threshold), float(margin)))
    return best[1], best[2]


def panel_report(panel, rows, threshold, margin):
    result = metrics(panel, threshold, margin)
    result["per_cow"] = {}
    for cow in np.unique(panel.truth):
        keep = panel.truth == cow
        sub = Scores(*(getattr(panel, key)[keep] for key in panel.__dataclass_fields__))
        result["per_cow"][str(cow)] = metrics(sub, threshold, margin)
    # Retain current production geometry's coverage ceiling separately.
    eligible = np.array(
        [
            row["minimum_side"] >= 64 and not row["clipped"] and row["overlap"] <= 0.2
            for row in rows
        ]
    )
    result["production_geometry_known_fraction"] = float(np.mean(eligible[panel.known]))
    return result


def experiment(manifest, vectors):
    rows = manifest["rows"]
    results = {}
    for method in ("legacy3", "uniform10", "diverse5", "diverse10"):
        selected = select_gallery(rows, vectors, method)
        gallery_ids = np.array([rows[i]["cow"] for i in selected])
        for adaptation in (False, True):
            transform = (
                whitening(vectors[selected], gallery_ids) if adaptation else normalize
            )
            gallery = transform(vectors[selected])
            for pooling in (1, 3, 5):
                panels = {}
                for name in ("development", "development_later", "calibration"):
                    positions = [
                        i for i, row in enumerate(rows) if row["panel"] == name
                    ]
                    selected_rows = [rows[i] for i in positions]
                    queries = pooled_queries(
                        selected_rows, transform(vectors[positions]), pooling
                    )
                    truth = np.array([row["cow"] for row in selected_rows])
                    panels[name] = score(
                        gallery, gallery_ids, queries, truth, np.zeros(len(truth))
                    )
                threshold, margin = calibrate_target(panels["calibration"])
                key = f"{method}-{'whitened' if adaptation else 'raw'}-pool{pooling}"
                results[key] = {
                    "gallery_rows": selected.tolist(),
                    "threshold": threshold,
                    "margin": margin,
                    "panels": {
                        name: panel_report(
                            panel,
                            [row for row in rows if row["panel"] == name],
                            threshold,
                            margin,
                        )
                        for name, panel in panels.items()
                    },
                    "default_fixed_policy": {
                        name: metrics(panel, 0.65, 0.1)
                        for name, panel in panels.items()
                    },
                }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_text())
    if digest(args.run / "vectors.npz") != manifest["vectors_sha256"]:
        raise ValueError("Recorded feature cache changed")
    with np.load(args.run / "vectors.npz", allow_pickle=False) as archive:
        vectors = archive["vectors"]
    result = {
        "status": "Exploratory development: no final windows opened",
        "limitation": "Publisher boxes and true track IDs; recognition-only diagnostic, not deployed tracking accuracy",
        "manifest_sha256": digest(args.run / "manifest.json"),
        "script_sha256": digest(Path(__file__)),
        "conditions": experiment(manifest, vectors),
    }
    write_json(args.run / "experiments.json", result)
    for name, condition in result["conditions"].items():
        print(
            name,
            json.dumps(
                {
                    split: {
                        key: values[key]
                        for key in (
                            "accepted_precision",
                            "known_coverage",
                            "unknown_false_acceptance_rate",
                            "known_rank1",
                        )
                    }
                    for split, values in condition["panels"].items()
                }
            ),
        )


if __name__ == "__main__":
    main()
