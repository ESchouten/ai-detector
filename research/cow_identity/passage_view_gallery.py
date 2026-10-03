"""Store only independently accepted frozen first-day chronological examples."""

import json
from pathlib import Path

import cv2
from benchmark import digest, write_json
from passage_crop_audit import tile
from passage_query import save_references
from passage_view_enrollment import OUTPUT as CANDIDATES
from passage_view_enrollment import PROTOCOL, SOURCE
from PIL import Image

from aidetector.adapters.identity_catalog import (
    Catalog,
    EnrolledIdentity,
    IdentityCatalog,
)

OUTPUT = Path(".cache/cow-passage-gallery-views")
RESULTS = Path(__file__).parent / "results/2026-10-03"
REVIEWS = tuple(
    RESULTS / f"purdue-view-enrollment-review-{name}.json"
    for name in ("audit", "cattle")
)


def reviewed_candidates():
    protocol = json.loads(PROTOCOL.read_text())
    for path, expected in protocol["files"].items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Frozen enrollment input changed:{path}")
    candidates = json.loads((CANDIDATES / "candidates.json").read_text())["candidates"]
    decisions = []
    for path in REVIEWS:
        review = json.loads(path.read_text())
        if review["protocol_sha256"] != digest(PROTOCOL) or review[
            "candidates_sha256"
        ] != digest(CANDIDATES / "candidates.json"):
            raise ValueError("Review belongs to another frozen selection")
        decisions.extend(review["rows"])
    decisions.sort(key=lambda row: row["candidate"])
    if [row["candidate"] for row in decisions] != list(range(len(candidates))):
        raise ValueError("Every fixed candidate must be reviewed exactly once")
    return candidates, decisions


def prepare():
    if OUTPUT.exists():
        raise ValueError("Preserve the frozen chronological gallery")
    candidates, decisions = reviewed_candidates()
    labels = json.loads((RESULTS / "purdue-passage-labels.json").read_text())["clips"]
    base = json.loads(
        (Path(__file__).with_name("passage_torso_protocol.json")).read_text()
    )
    source = json.loads((SOURCE / "proposals.json").read_text())
    accepted = {cow: [] for cow in base["known_cows"]}
    for decision in decisions:
        if not decision["accepted"]:
            continue
        row = candidates[decision["candidate"]]
        cow = decision["cow"]
        if cow not in accepted or cow != labels[row["clip"]]["principal_cow"]:
            raise ValueError("An accepted reference is not a known principal animal")
        accepted[cow].append(row["source_row"])
        source["rows"][row["source_row"]]["eligible"] = True
    catalog = IdentityCatalog(OUTPUT)
    identities = []
    montage = Image.new("RGB", (2600, 280 * len(accepted)), "white")
    for row_index, (cow, indices) in enumerate(accepted.items()):
        if len(indices) > 10:
            raise ValueError("More than ten reference images for one cow")
        samples = save_references(catalog, source, indices, SOURCE)
        identities.append(
            EnrolledIdentity(id=f"{cow:032x}", name=str(cow), samples=samples)
        )
        for column, index in enumerate(indices):
            row = source["rows"][index]
            image = cv2.imread(str(SOURCE / row["path"]))
            montage.paste(
                tile(image, [f"cow{cow}; source row{index}", f"second{row['second']}"]),
                (260 * column, 280 * row_index),
            )
    document = Catalog(revision=1, identities=tuple(identities))
    (OUTPUT / "catalog.json").write_text(document.model_dump_json(indent=2))
    montage.save(OUTPUT / "confirmed-gallery.jpg")
    provenance = {
        "protocol_sha256": digest(PROTOCOL),
        "candidate_manifest_sha256": digest(CANDIDATES / "candidates.json"),
        "review_sha256": {str(path): digest(path) for path in REVIEWS},
        "source_sha256": digest(Path(__file__)),
        "selected_source_rows": accepted,
        "reference_count": sum(len(indices) for indices in accepted.values()),
        "candidate_count": len(candidates),
        "review": "Independent AI-assisted source-context review, not external human-certified labels. No query feedback or backfilling.",
        "known_counts": {str(cow): len(indices) for cow, indices in accepted.items()},
    }
    write_json(OUTPUT / "provenance.json", provenance)
    write_json(RESULTS / "purdue-view-enrollment-summary.json", provenance)
    print(json.dumps(provenance))


if __name__ == "__main__":
    prepare()
