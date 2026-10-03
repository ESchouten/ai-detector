"""Count names lost by permanent binding removal; cached geometry stays unchanged."""

import json
from pathlib import Path
from types import SimpleNamespace

from benchmark import digest, write_json
from detection_birth_losses import frame_outcomes
from video_assessment import annotations, truth_at

ROOT = Path(__file__).parent
RUN = Path(".cache/cow-cutie/crowded-births/streaming.json")
INVENTORY = ROOT / "results/2026-10-03/detection/departure-inventory.json"
OFFICIAL = ROOT / "results/2026-10-03/detection/crowded-births.json"
OUTPUT = ROOT / "results/2026-10-03/detection/retirement-name-burden.json"
WINDOWS = ((330, 629), (930, 1229), (1230, 1529))


def longest_visible_gap(rows, named_key):
    """A missing publisher annotation interrupts rather than proves absence."""
    spans, run = [], []
    for row in rows:
        gap = row["present"] and not row[named_key]
        if run and (not gap or row["second"] != run[-1]["second"] + 1):
            spans.append(run)
            run = []
        if gap:
            run.append(row)
    if run:
        spans.append(run)
    if not spans:
        return None
    longest = max(spans, key=lambda span: (len(span), -span[0]["second"]))
    return {
        "start": longest[0]["second"],
        "end": longest[-1]["second"],
        "samples_1hz": len(longest),
        "observed_span_seconds": longest[-1]["second"] - longest[0]["second"],
        "right_censored": longest[-1]["second"] == rows[-1]["second"],
    }


def run():
    if OUTPUT.exists():
        raise ValueError("Keep earlier diagnostics unchanged")
    value, inventory, official = [
        json.loads(path.read_text()) for path in (RUN, INVENTORY, OFFICIAL)
    ]
    if (
        not value["complete"]
        or inventory["sources"][str(RUN)] != digest(RUN)
        or official["sources"][str(RUN)] != digest(RUN)
    ):
        raise ValueError("Use the same completed births-only run")
    args = SimpleNamespace(
        annotations=Path("datasets/8-calves/video/pmfeed_4_3_16.safe-v1.npz"),
        source_pickle=Path("datasets/8-calves/video/pmfeed_4_3_16.pkl"),
    )
    records, _ = annotations(args)
    exposed = (records["frame_id"] >= 1) & (records["frame_id"] <= 1529 * 20 + 1)
    records = {key: array[exposed] for key, array in records.items()}
    triggers = {
        int(cow): row["first_potential_retirement"]["five_second_trigger"]
        for cow, row in inventory["crowded"]["objects"].items()
        if int(cow) <= 6 and row["first_potential_retirement"] is not None
    }
    rows = {cow: [] for cow in range(1, 7)}
    for frame in value["timeline"]:
        if not 0 <= frame["second"] <= 1529:
            raise ValueError("Only the exposed baseline is permitted")
        truth = truth_at(records, frame["publisher_frame"], 800, 600)
        outcomes = frame_outcomes(frame, truth)
        for cow in rows:
            correct = outcomes.get(cow, {}).get("correct", False)
            retired = cow in triggers and frame["second"] >= triggers[cow]
            rows[cow].append(
                {
                    "second": frame["second"],
                    "present": cow in outcomes,
                    "correct_before": correct,
                    "correct_after": correct and not retired,
                }
            )
    panels = {}
    for start, stop in WINDOWS:
        subset = {
            cow: [row for row in cow_rows if start <= row["second"] <= stop]
            for cow, cow_rows in rows.items()
        }
        flat = [row for cow_rows in subset.values() for row in cow_rows]
        counts = official["conditions"][str(start)]["naming_counts"]
        assert sum(r["present"] for r in flat) == counts["visible_known"]
        assert sum(r["correct_before"] for r in flat) == counts["correct_name"]
        panels[str(start)] = {
            "visible_known": counts["visible_known"],
            "original_correct_names": counts["correct_name"],
            "previously_correct_names_removed": sum(
                r["correct_before"] and not r["correct_after"] for r in flat
            ),
            "by_cow": {
                str(cow): {
                    "original_correct_names": sum(r["correct_before"] for r in rr),
                    "previously_correct_names_removed": sum(
                        r["correct_before"] and not r["correct_after"] for r in rr
                    ),
                    "longest_original_correct_name_gap_while_annotated": longest_visible_gap(
                        rr, "correct_before"
                    ),
                    "longest_after_binding_removed_gap_while_annotated": longest_visible_gap(
                        rr, "correct_after"
                    ),
                }
                for cow, rr in subset.items()
            },
        }
    sources = [
        RUN,
        INVENTORY,
        OFFICIAL,
        args.annotations,
        args.source_pickle,
        Path(__file__),
        ROOT / "detection_birth_losses.py",
        ROOT / "video_assessment.py",
    ]
    result = {
        "scope": "CPU binding-only overlay: first5s zero-mask retirement permanently removes that original name; no automatic return, no score-based threshold choice and no inference.",
        "sources": {str(path): digest(path) for path in sources},
        "first_binding_removal_seconds": triggers,
        "panels": panels,
        "full_exposed_visible_gaps": {
            str(cow): {
                key: longest_visible_gap(rr, key)
                for key in ("correct_before", "correct_after")
            }
            for cow, rr in rows.items()
        },
        "confirmation_burden": "One previously named track loses its binding in this baseline. Regaining its name would require at least one explicit new confirmation on an unambiguous current anonymous object; successful new-object creation is not established by this overlay.",
        "limitation": "This is an optimistic compatibility calculation on untouched cached geometry. Real SDK retirement changes competition, memory and subsequent births, so these are not predicted post-retirement metrics. Missing publisher annotations break visible-gap spans; they do not prove physical absence. No alternative acceptance score is computed.",
    }
    write_json(OUTPUT, result)
    print(digest(OUTPUT))


if __name__ == "__main__":
    run()
