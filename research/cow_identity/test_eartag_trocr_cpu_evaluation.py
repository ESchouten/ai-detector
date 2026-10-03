"""Reject incomplete, repeated or nonfinite training before a pilot can be scored."""

import copy
import random

import pytest
from eartag_trocr_cpu_evaluation import validate_training


def training_fixture():
    recipe = {"epochs": 2, "seed": 7, "batch": 2, "accumulation": 2}
    steps = []
    for epoch in range(2):
        order = list(range(5))
        random.Random(7 + epoch).shuffle(order)
        steps.extend(
            {
                "epoch": epoch,
                "indices": order[i : i + 4],
                "loss": 1.0,
                "gradient_norm": 2.0,
            }
            for i in (0, 4)
        )
    report = {
        "complete": True,
        "error": None,
        "mode": "train",
        "actual_device": "cpu",
        "precision": "float32",
        "threads": 2,
        "protocol_sha256": "fixed",
        "checkpoint_files": {"model": "hash"},
        "steps": steps,
    }
    return report, recipe


def test_training_report_requires_exact_complete_order_and_finite_gradients():
    report, recipe = training_fixture()
    validate_training(report, "fixed", 5, recipe)
    for mutation in ("missing", "repeated", "nan", "preflight", "protocol"):
        bad = copy.deepcopy(report)
        if mutation == "missing":
            bad["steps"].pop()
        elif mutation == "repeated":
            bad["steps"][1]["indices"] = bad["steps"][0]["indices"]
        elif mutation == "nan":
            bad["steps"][0]["gradient_norm"] = float("nan")
        elif mutation == "preflight":
            bad["mode"] = "preflight"
        else:
            bad["protocol_sha256"] = "different"
        with pytest.raises(ValueError, match="complete finite"):
            validate_training(bad, "fixed", 5, recipe)
