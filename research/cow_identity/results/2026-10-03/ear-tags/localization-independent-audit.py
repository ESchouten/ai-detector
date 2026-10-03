"""Independent no-model recount using publisher text labels and bipartite matching."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path.cwd()
HERE = Path(__file__).parent
PROTOCOL = ROOT / "research/cow_identity/eartag_localization_evaluate_protocol.json"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    total = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / total if total else 0


def match(predicted, truth):
    neighbors = [
        [j for j, t in enumerate(truth) if iou(p, t) >= 0.5] for p in predicted
    ]
    owner = {}

    def augment(p, visited):
        for t in neighbors[p]:
            if t in visited:
                continue
            visited.add(t)
            if t not in owner or augment(owner[t], visited):
                owner[t] = p
                return True
        return False

    for p in range(len(predicted)):
        augment(p, set())
    return owner


def count(predicted, truth):
    pairs = match(predicted, truth)
    return dict(
        truth=len(truth),
        predicted=len(predicted),
        matched=len(pairs),
        missed=len(truth) - len(pairs),
        unmatched_predictions=len(predicted) - len(pairs),
    ), set(pairs)


def category(n):
    return "<16" if n < 16 else "16–32" if n < 32 else "32–64" if n < 64 else ">=64"


def publisher_truth(label_path, width, height, expected):
    truth = []
    for line in label_path.read_text().splitlines():
        cls, x, y, w, h = map(float, line.split())
        assert cls == 0
        truth.append(
            [
                (x - w / 2) * width,
                (y - h / 2) * height,
                (x + w / 2) * width,
                (y + h / 2) * height,
            ]
        )
    assert len(truth) == len(expected)
    for a, b in zip(truth, expected, strict=True):
        assert max(abs(x - y) for x, y in zip(a, b["xyxy"], strict=True)) < 1e-8
    return truth


def main():
    protocol = json.loads(PROTOCOL.read_text())
    raw_path = HERE / "localization-raw.json"
    score_path = HERE / "localization-score.json"
    raw = json.loads(raw_path.read_text())
    score = json.loads(score_path.read_text())
    assert raw["protocol_sha256"] == score["protocol_sha256"] == digest(PROTOCOL)
    assert score["raw_sha256"] == digest(raw_path)
    for path, value in protocol["files"].items():
        assert digest(path) == value, path
    assert len(raw["rows"]) == len(protocol["rows"]) == 11
    tags = {
        r["id"]: r
        for r in json.loads((HERE / "ownership-subset-inventory.json").read_text())[
            "rows"
        ]
    }
    heads = {
        r["id"]: r
        for r in json.loads((HERE / "ownership-oracle-draft.json").read_text())["rows"]
    }
    original = {r["id"]: r for r in score["details"]}
    panels = defaultdict(lambda: defaultdict(int))
    head_total = defaultdict(int)
    bins = defaultdict(lambda: dict(truth=0, matched=0))
    details = []
    labels = {}
    for expected, row in zip(protocol["rows"], raw["rows"], strict=True):
        assert all(row[k] == v for k, v in expected.items())
        assert row["device"] in {"mps", "mps:0"} and row["fp16"] is False
        height, width = row["shape"][:2]
        label_path = (ROOT / row["image"]).with_suffix(".txt")
        labels[str(label_path.relative_to(ROOT))] = digest(label_path)
        truth = publisher_truth(label_path, width, height, tags[row["id"]]["tags"])
        predicted = [b["xyxy"] for b in row["boxes"] if b["class"] == 1]
        counts, matched = count(predicted, truth)
        assert counts == {
            k: v for k, v in original[row["id"]]["tag"].items() if k != "pairs"
        }
        for k, v in counts.items():
            panels[row["panel"]][k] += v
        gain = min(row["input_shape"][2] / height, row["input_shape"][3] / width)
        for j, box in enumerate(truth):
            side = min(box[2] - box[0], box[3] - box[1])
            for unit, factor in [("native", 1), ("input", gain)]:
                entry = bins[f"{row['panel']}/{unit}/{category(side * factor)}"]
                entry["truth"] += 1
                entry["matched"] += int(j in matched)
        detail = {"id": row["id"], "tag": counts}
        if row["panel"] == "development":
            hc, _ = count(
                [b["xyxy"] for b in row["boxes"] if b["class"] == 0],
                [b["xyxy"] for b in heads[row["id"]]["heads"]],
            )
            assert hc == {
                k: v for k, v in original[row["id"]]["head"].items() if k != "pairs"
            }
            for k, v in hc.items():
                head_total[k] += v
            detail["head"] = hc
        details.append(detail)
    assert dict(panels) == score["panels"]
    assert dict(head_total) == score["development_heads"]
    assert dict(bins) == score["tag_size_bins"]
    report = dict(
        status="PASS_INDEPENDENT_RECOUNT",
        protocol_sha256=digest(PROTOCOL),
        raw_sha256=digest(raw_path),
        score_sha256=digest(score_path),
        audit_source_sha256=digest(__file__),
        verified_bindings=len(protocol["files"]),
        source_images=11,
        publisher_tag_labels=labels,
        panels=dict(panels),
        development_heads=dict(head_total),
        tag_size_bins=dict(bins),
        details=details,
        scope="No model/scorer helper calls; direct original normalized publisher rectangles, all uncertain/clipped reviewed heads retained, independent maximum-cardinality IoU>=0.5 matching. Count verification does not certify labels or scene independence.",
    )
    output = HERE / "localization-independent-audit.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["panels"], report["development_heads"], digest(output))


if __name__ == "__main__":
    main()
