"""Select bounded human-confirmed references from actual development detections.

The first development window becomes enrollment in this separate experiment.
It is never scored as a query panel after its labels have been revealed.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_compare import load
from recognition_enrollment import PROTOCOL as ENROLLMENT_PROTOCOL
from recognition_enrollment import enroll
from recognition_experiment import select_gallery
from recognition_fusion import observation_key, representation


def prepare(args):
    from tracked_experiment import (
        PROTOCOL,
        validate_gallery,
        validate_panel,
        validate_representation,
    )

    protocol = json.loads(PROTOCOL.read_text())
    enrollment = json.loads(ENROLLMENT_PROTOCOL.read_text())
    original, original_vectors = load(args.original_gallery)
    gallery, gallery_vectors = load(args.gallery)
    additional, additional_vectors = load(args.additional)
    validate_gallery(original, protocol)
    validate_gallery(gallery, protocol)
    validate_panel(additional, gallery, "development", protocol)
    validate_representation(gallery, additional, "additional enrollment")
    lookup = {observation_key(row): i for i, row in enumerate(gallery["rows"])}
    initial = [
        lookup[observation_key(original["rows"][i])]
        for i in select_gallery(original["rows"], original_vectors, args.selection)
    ]
    # Keep only the chosen early references. The new rows are real detections;
    # their truth labels are read only as the response inside enroll().
    rows = [gallery["rows"][i] for i in initial] + [
        {**row, "cow": row["truth"]} for row in additional["rows"]
    ]
    vectors = np.concatenate([gallery_vectors[initial], additional_vectors])
    selected, prompts = enroll(rows, vectors, range(len(initial)), enrollment)
    sources = [{"archive": "initial", "row": i} for i in initial] + [
        {"archive": "additional", "row": i} for i in range(len(additional["rows"]))
    ]
    references = [
        {
            **sources[i],
            "cow": rows[i]["cow"],
            "observation": {
                key: rows[i].get(key)
                for key in ("frame", "second", "box", "track", "pixels_sha256")
            },
        }
        for i in selected
    ]
    for prompt in prompts:
        index = prompt.pop("row")
        prompt["source"] = sources[index]
        prompt["track"] = rows[index]["track"]
    args.output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(args.output / "vectors.npz", vectors=vectors[selected])
    result = {
        "scope": "Actual predicted crops; idealized human response via publisher matching; unmatched prompts cannot enroll a reference. No query result or final-test evidence.",
        "protocol_sha256": digest(ENROLLMENT_PROTOCOL),
        "initial_selection": args.selection,
        "representation_fingerprint": representation(gallery["contract"]),
        "sources": {
            "initial": {
                "path": str(args.gallery),
                "manifest_sha256": digest(args.gallery / "manifest.json"),
            },
            "additional": {
                "path": str(args.additional),
                "manifest_sha256": digest(args.additional / "manifest.json"),
            },
        },
        "vectors_sha256": digest(args.output / "vectors.npz"),
        "references": references,
        "prompts": prompts,
        "counts": {
            "questions": len(prompts),
            "outcomes": dict(Counter(prompt["outcome"] for prompt in prompts)),
            "references_per_cow": dict(Counter(row["cow"] for row in references)),
        },
        "calibration_window": enrollment["calibration_seconds"],
        "development_window": enrollment["development_seconds"],
    }
    write_json(args.output / "references.json", result)
    print(json.dumps(result["counts"]))
    return result


def read_references(path, gallery_path, gallery, gallery_vectors, protocol):
    """Reconstruct confirmed features from their verified source archives."""
    from tracked_experiment import validate_panel, validate_representation

    result = json.loads(path.read_text())
    if result["protocol_sha256"] != digest(ENROLLMENT_PROTOCOL):
        raise ValueError("Additional enrollment differs from the frozen protocol")
    sources = result["sources"]
    if sources["initial"]["manifest_sha256"] != digest(gallery_path / "manifest.json"):
        raise ValueError("Confirmed references use a different initial gallery")
    additional_path = Path(sources["additional"]["path"])
    if (
        digest(additional_path / "manifest.json")
        != sources["additional"]["manifest_sha256"]
    ):
        raise ValueError("Additional enrollment source changed")
    additional, extra_vectors = load(additional_path)
    validate_panel(additional, gallery, "development", protocol)
    validate_representation(gallery, additional, "additional enrollment")
    if result["representation_fingerprint"] != representation(gallery["contract"]):
        raise ValueError("Confirmed references use a different representation")
    archives = {
        "initial": (gallery, gallery_vectors),
        "additional": (additional, extra_vectors),
    }
    vectors, owners = confirmed_arrays(
        result["references"], archives, protocol["known_ids"]
    )
    return (
        vectors,
        owners,
        {
            "method": "Bounded actual-box human confirmations; early development becomes enrollment",
            "references_sha256": digest(path),
            "counts": result["counts"],
            "source_manifests": sources,
        },
    )


def confirmed_arrays(references, archives, known_ids):
    owners, vectors, seen = [], [], set()
    totals, additions = Counter(), Counter()
    for reference in references:
        archive, index, cow = reference["archive"], reference["row"], reference["cow"]
        source, features = archives[archive]
        if type(index) is not int or not 0 <= index < len(source["rows"]):
            raise ValueError("Invalid confirmed source index")
        row = source["rows"][index]
        actual_cow = row["cow"] if archive == "initial" else row["truth"]
        if cow not in known_ids or cow != actual_cow:
            raise ValueError(
                "Confirmed references cannot enroll unknown or mislabeled cows"
            )
        if archive == "initial" and row["panel"] != "enrollment":
            raise ValueError("Initial references must come from early enrollment")
        key = (archive, index)
        if key in seen:
            raise ValueError("Confirmed references contain duplicate photos")
        seen.add(key)
        totals[cow] += 1
        additions[cow] += archive == "additional"
        owners.append(cow)
        vectors.append(features[index])
    if (
        set(totals) != set(known_ids)
        or max(totals.values()) > 10
        or max(additions.values()) > 2
    ):
        raise ValueError("Confirmed gallery exceeds the frozen reference budget")
    return np.asarray(vectors), np.asarray(owners)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-gallery", "gallery", "additional", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--selection", choices=("diverse10", "uniform10"), default="diverse10"
    )
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
