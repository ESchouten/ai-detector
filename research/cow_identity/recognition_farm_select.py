"""Select a farm checkpoint using only frozen calibration and external guards."""

import argparse
import json
from pathlib import Path

from benchmark import digest, write_json

PROTOCOL = Path(__file__).with_name("recognition_farm_training_protocol.json")


def guard_passes(metrics, guard):
    return (
        metrics["known_coverage"] >= guard["minimum_known_coverage"]
        and (metrics["accepted_precision"] or 0) >= guard["minimum_precision"]
        and metrics["unknown_false_acceptance_rate"] is not None
        and metrics["unknown_false_acceptance_rate"]
        <= guard["maximum_unknown_false_acceptance"]
    )


def decision_key(metrics):
    counts = metrics["counts"]
    wrong = (
        counts["wrong_known_names"]
        + counts["unknown_named"]
        + counts["unmatched_named"]
    )
    return counts["correct_names"], -wrong


def select(args):
    protocol = json.loads(PROTOCOL.read_text())
    if digest(args.run / "selection-protocol.json") != digest(PROTOCOL):
        raise ValueError("Training selection protocol differs from the frozen study")
    training = json.loads((args.run / "report.json").read_text())
    if (
        training["protocol"]["enrollment_manifest_sha256"]
        != protocol["enrollment_manifest_sha256"]
        or training["completed_steps"] != 200
    ):
        raise ValueError("Training did not follow the frozen enrollment or step budget")
    checkpoints = {
        record["step"]: record
        for record in [training["baseline"], *training["checkpoints"]]
    }
    if sorted(checkpoints) != protocol["checkpoints"]:
        raise ValueError("Expected baseline plus both frozen checkpoints")
    comparisons = {}
    for step, record in checkpoints.items():
        path = args.evaluation / f"step-{step:03d}" / "calibration.json"
        report = json.loads(path.read_text())
        if any(
            set(value["panels"]) != {"calibration"}
            for value in report["conditions"].values()
        ):
            raise ValueError(
                "Checkpoint selection must not inspect development results"
            )
        expected = (
            protocol["base_encoder_fingerprint"]
            if step == 0
            else record["encoder_fingerprint"]
        )
        representation = report["inputs"]["calibration"]["representation"]
        if (
            representation["encoder_fingerprint"] != expected
            or representation["variant"] != "masked"
        ):
            raise ValueError("Calibration used the wrong checkpoint or representation")
        name, condition = max(
            sorted(report["conditions"].items()),
            key=lambda item: decision_key(item[1]["panels"]["calibration"]),
        )
        comparisons[step] = {
            "external_guard_passed": guard_passes(
                record["validation"], protocol["external_regression_guard"]
            ),
            "external_validation": record["validation"],
            "calibration_report_sha256": digest(path),
            "condition": name,
            "policy": {
                "threshold": condition["threshold"],
                "margin": condition["margin"],
            },
            "calibration": condition["panels"]["calibration"],
            "weights_sha256": record.get(
                "weights_sha256", protocol["initial_weights_sha256"]
            ),
        }
    eligible = [
        step for step, value in comparisons.items() if value["external_guard_passed"]
    ]
    selected = max(
        eligible,
        key=lambda step: (*decision_key(comparisons[step]["calibration"]), -step),
    )
    result = {
        "protocol_sha256": digest(PROTOCOL),
        "training_report_sha256": digest(args.run / "report.json"),
        "selected_step": selected,
        "comparisons": comparisons,
        "scope": "Calibration selection only; development and reserved final windows not used",
    }
    write_json(args.output, result)
    print(json.dumps({"selected_step": selected, **comparisons[selected]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "evaluation", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    select(parser.parse_args())


if __name__ == "__main__":
    main()
