"""Simulate a bounded number of additional human enrollment confirmations.

Candidates are chosen with embeddings and geometry before their publisher label
is revealed as a human response. All requests count, including unknown animals.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_compare import load, row_key, verify_source
from recognition_experiment import calibrate_target, panel_report, select_gallery
from scoring import score

PROTOCOL = Path(__file__).with_name("recognition_enrollment_protocol.json")


def rank_candidates(indices, vectors, gallery, owners, asked, protocol):
    similarity = vectors[indices] @ vectors[gallery].T
    by_cow = np.stack(
        [similarity[:, owners == cow].max(axis=1) for cow in np.unique(owners)], axis=1
    )
    ranked = np.sort(by_cow, axis=1)
    best = ranked[:, -1]
    margin = best - ranked[:, -2]
    choices = []
    for index, confidence, gap in zip(indices, best, margin, strict=True):
        if confidence >= 0.65 and gap >= 0.10:
            continue
        if (
            asked
            and (vectors[asked] @ vectors[index]).max()
            >= protocol["prompt_duplicate_similarity"]
        ):
            continue
        choices.append((float(confidence), float(gap), index))
    return sorted(choices)


def replace_reference(gallery, new, vectors, rows, confirmed):
    cow = rows[new]["cow"]
    same_cow = [i for i in gallery if rows[i]["cow"] == cow] + [new]
    similarity = vectors[same_cow] @ vectors[same_cow].T
    np.fill_diagonal(similarity, -np.inf)
    redundancy = similarity.max(axis=1)
    original = [i for i, index in enumerate(same_cow) if index not in confirmed]
    drop = max(original, key=lambda i: (float(redundancy[i]), -same_cow[i]))
    return [index for index in gallery if index != same_cow[drop]] + [new]


def enroll(rows, vectors, initial, protocol):
    gallery = list(initial)
    known = {rows[i]["cow"] for i in gallery}
    confirmations = Counter()
    asked, confirmed, prompts = [], set(), []
    start, end = protocol["extra_enrollment_seconds"]
    quality = protocol["candidate_quality"]
    for second in range(start, end + 1, protocol["candidate_cadence_seconds"]):
        if len(prompts) >= protocol["question_budget"]:
            break
        indices = [
            i
            for i, row in enumerate(rows)
            if row["second"] == second
            and not row["clipped"]
            and row["minimum_side"] >= quality["minimum_side"]
            and row["overlap"] <= quality["maximum_overlap"]
        ]
        if not indices:
            continue
        owners = np.array([rows[i]["cow"] for i in gallery])
        choices = rank_candidates(indices, vectors, gallery, owners, asked, protocol)
        if not choices:
            continue
        similarity, margin, selected = choices[0]
        asked.append(selected)
        # Only now is truth exposed, as an idealized response by the farmer.
        cow = rows[selected]["cow"]
        outcome = (
            "unmatched detection remains unenrolled"
            if cow is None
            else "unknown remains unenrolled"
        )
        if cow in known:
            outcome = "known cow already at confirmation cap"
            if confirmations[cow] < protocol["maximum_new_references_per_cow"]:
                confirmations[cow] += 1
                confirmed.add(selected)
                gallery = replace_reference(gallery, selected, vectors, rows, confirmed)
                outcome = "reference confirmed"
        prompts.append(
            {
                "second": second,
                "row": selected,
                "cow": cow,
                "similarity": similarity,
                "margin": margin,
                "outcome": outcome,
            }
        )
    return gallery, prompts


def evaluate(rows, vectors, gallery):
    owners = np.array([rows[i]["cow"] for i in gallery])
    panels, panel_rows = {}, {}
    for name in ("development_later", "calibration"):
        positions = [
            i
            for i, row in enumerate(rows)
            if row["panel"] == name and row["second"] % 5 == 0
        ]
        selected_rows = [rows[i] for i in positions]
        truth = np.array([row["cow"] for row in selected_rows])
        panels[name] = score(
            vectors[gallery], owners, vectors[positions], truth, np.zeros(len(truth))
        )
        panel_rows[name] = selected_rows
    threshold, margin = calibrate_target(panels["calibration"])
    return {
        "threshold": threshold,
        "margin": margin,
        "panels": {
            name: panel_report(panel, panel_rows[name], threshold, margin)
            for name, panel in panels.items()
        },
    }


def experiment(baseline, run, protocol):
    base_manifest, base_vectors = load(baseline)
    manifest, vectors = load(run)
    verify_source(baseline, base_manifest, manifest)
    rows = manifest["rows"]
    lookup = {row_key(row): i for i, row in enumerate(rows)}
    result = {
        "manifest_sha256": digest(run / "manifest.json"),
        "encoder_fingerprint": manifest["contract"]["encoder_fingerprint"],
        "conditions": {},
    }
    for method in ("diverse10", "uniform10"):
        initial = [
            lookup[row_key(base_manifest["rows"][i])]
            for i in select_gallery(base_manifest["rows"], base_vectors, method)
        ]
        gallery, prompts = enroll(rows, vectors, initial, protocol)
        result["conditions"][method] = {
            "initial_gallery_rows": initial,
            "updated_gallery_rows": gallery,
            "questions": len(prompts),
            "confirmed_new_references": dict(
                Counter(
                    p["cow"] for p in prompts if p["outcome"] == "reference confirmed"
                )
            ),
            "prompt_outcomes": dict(Counter(p["outcome"] for p in prompts)),
            "prompts": prompts,
            "before": evaluate(rows, vectors, initial),
            "after": evaluate(rows, vectors, gallery),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text())
    result = {"protocol": protocol, "protocol_sha256": digest(PROTOCOL), "runs": {}}
    for run in args.runs:
        result["runs"][run.name] = experiment(args.baseline, run, protocol)
    write_json(args.output, result)
    for name, run in result["runs"].items():
        for method, condition in run["conditions"].items():
            print(
                json.dumps(
                    {
                        "run": name,
                        "gallery": method,
                        "questions": condition["questions"],
                        "outcomes": condition["prompt_outcomes"],
                        "before": condition["before"]["panels"]["development_later"],
                        "after": condition["after"]["panels"]["development_later"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
