import collections
import hashlib
import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

base = Path(".cache/cow-application-bootstrap")
report_path = Path(
    "research/cow_identity/results/2026-10-03/detection/application-bootstrap.json"
)
report = json.loads(report_path.read_text())
protocol = Path("research/cow_identity/application_bootstrap_protocol.json")
recipe = json.loads(protocol.read_text())


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


assert report["status"] == "PASS" and report["protocol_sha256"] == digest(protocol)
assert all(digest(path) == value for path, value in recipe["files"].items())
with sqlite3.connect(base / "data/identities/automatic/profiles.sqlite") as db:
    facts = [json.loads(row[0]) for row in db.execute("SELECT facts FROM candidates")]
    scopes = [json.loads(row[0]) for row in db.execute("SELECT scope FROM profiles")]
    images = list(db.execute("SELECT id,jpeg FROM images"))
    assert len(facts) == 43 and len(scopes) == 15 and len(images) == 11
    assert sorted(facts, key=lambda f: f["id"]) == sorted(
        report["saved_facts"], key=lambda f: f["id"]
    )
    for key, data in images:
        assert hashlib.sha256(data).hexdigest() == key
        assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape == (
            600,
            800,
            3,
        )
source0 = hashlib.sha256(b"0").hexdigest()
assert {x["source_key"] for x in scopes} == {source0}
assert {tuple(x["image_shape"]) for x in facts} == {(600, 800, 3)}
assert all(not {"name", "identity_id", "ear_number"} & set(x) for x in facts)
assert all(
    x["status"] == "anonymous_observation_not_biological_identity" for x in facts
)
epochs = collections.Counter(x["epoch"] for x in facts)
assert sorted(epochs.values()) == [19, 24]
sets = [
    {(x["instance_id"], x["generation"]) for x in facts if x["epoch"] == epoch}
    for epoch in epochs
]
assert not sets[0] & sets[1]
a = report["audit"]
assert len(a["observations"]) == 162 and len(a["evidence"]) == 369
assert all(0 <= x["age"] < 1 for x in a["observations"] + a["evidence"])
assert collections.Counter(x["source"] for x in a["observations"]) == {
    "0": 50,
    "1": 112,
}
assert report["captures"]["opened"] == report["captures"]["released"] == [0, 1, 0]
assert a["closed"] == ["cutie", "yolo"]
assert not (base / "data/identities/catalog.json").exists()
assert not (base / "data/identities/embeddings.sqlite").exists()
assert not (base / "data/detections").exists()
value = {
    "status": "PASS",
    "report_sha256": digest(report_path),
    "protocol_sha256": digest(protocol),
    "source_bindings_rechecked_after_run": len(recipe["files"]),
    "native_image_shape": [600, 800, 3],
    "candidates": len(facts),
    "profiles": len(scopes),
    "shared_jpeg_images": len(images),
    "qualified_episodes": len({f["episode_id"] for f in facts}),
    "saved_by_epoch": dict(epochs),
    "source0_observations": 50,
    "synthetic_source1_observations": 112,
    "eligible_evidence_callbacks": 369,
    "maximum_observation_age_seconds": max(x["age"] for x in a["observations"]),
    "no_catalog_or_biological_labels": True,
    "no_event_archives_or_external_deliveries": True,
    "event_note": "The pipeline still assembled2continuous detector events and112ordinary snapshots; no exporters configured and no event archive written. These are not cow names.",
    "cleanup_note": "Recorded all three captures released and both real model contexts exited; runtime assertion found no capture/worker/preview threads remaining, SQLite exclusive write lock was acquired afterward. Idle SQLite handles are not individually inspected.",
}
Path(
    "research/cow_identity/results/2026-10-03/detection/application-bootstrap-audit.json"
).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
print(json.dumps(value, indent=2))
