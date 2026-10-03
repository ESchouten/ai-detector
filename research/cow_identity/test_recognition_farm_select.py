"""A high calf score cannot bypass the frozen external guard or query split."""

import json
from types import SimpleNamespace

import pytest
import recognition_farm_select as selection


def study(tmp_path, monkeypatch):
    protocol = {
        "enrollment_manifest_sha256": "enrollment",
        "checkpoints": [0, 100, 200],
        "base_encoder_fingerprint": "base",
        "initial_weights_sha256": "original",
        "external_regression_guard": {
            "minimum_known_coverage": 0.75,
            "minimum_precision": 0.99,
            "maximum_unknown_false_acceptance": 0.01,
        },
    }
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(protocol))
    monkeypatch.setattr(selection, "PROTOCOL", path)
    (tmp_path / "selection-protocol.json").write_text(path.read_text())
    checkpoints = []
    for step, correct in ((0, 10), (100, 100), (200, 10)):
        checkpoints.append(
            {
                "step": step,
                "encoder_fingerprint": str(step),
                "validation": {
                    "known_coverage": 0.5 if step == 100 else 0.8,
                    "accepted_precision": 0.995,
                    "unknown_false_acceptance_rate": 0.005,
                },
            }
        )
        folder = tmp_path / f"step-{step:03d}"
        folder.mkdir()
        result = {
            "inputs": {
                "calibration": {
                    "representation": {
                        "encoder_fingerprint": "base" if step == 0 else str(step),
                        "variant": "masked",
                    }
                }
            },
            "conditions": {
                "fixed": {
                    "threshold": 0.6,
                    "margin": 0.1,
                    "panels": {
                        "calibration": {
                            "counts": {
                                "correct_names": correct,
                                "wrong_known_names": 0,
                                "unknown_named": 0,
                                "unmatched_named": 0,
                            }
                        }
                    },
                }
            },
        }
        (folder / "calibration.json").write_text(json.dumps(result))
    (tmp_path / "report.json").write_text(
        json.dumps(
            {
                "protocol": {"enrollment_manifest_sha256": "enrollment"},
                "completed_steps": 200,
                "baseline": checkpoints[0],
                "checkpoints": checkpoints[1:],
            }
        )
    )
    return SimpleNamespace(
        run=tmp_path, evaluation=tmp_path, output=tmp_path / "selected.json"
    )


def test_external_guard_rejects_best_calibration_and_ties_keep_baseline(
    tmp_path, monkeypatch
):
    args = study(tmp_path, monkeypatch)
    selection.select(args)
    result = json.loads(args.output.read_text())
    assert result["selected_step"] == 0
    assert not result["comparisons"]["100"]["external_guard_passed"]


def test_development_results_cannot_enter_checkpoint_selection(tmp_path, monkeypatch):
    args = study(tmp_path, monkeypatch)
    path = tmp_path / "step-100/calibration.json"
    result = json.loads(path.read_text())
    result["conditions"]["fixed"]["panels"]["development_later"] = {}
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="must not inspect development"):
        selection.select(args)
