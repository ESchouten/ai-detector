"""Archive the completed fixed spatial-tail pilot; descriptive CPU checks only."""

import json
from pathlib import Path

import numpy as np
from benchmark import digest, write_json
from recognition_spatial_tail_train import inputs
from recognition_temporal_diagnosis import stages
from recognition_temporal_retrieval import describe

ROOT = Path(__file__).parent
FREEZE = ROOT / "recognition_spatial_tail_training_protocol.json"
RUN = Path(".cache/cow-spatial-tail-trained-v1")
OUTPUT = ROOT / "results/2026-10-03/recognition/spatial-tail-pilot.json"


def main():
    if OUTPUT.exists():
        raise FileExistsError("Preserve the completed fixed result")
    _, (protocol, _, _, original, manifest, _) = inputs(FREEZE)
    completed = json.loads((RUN / "calibration.json").read_text())
    training = json.loads((RUN / "training.json").read_text())
    if (
        completed["freeze_sha256"] != digest(FREEZE)
        or completed["adapted_vectors_sha256"] != digest(RUN / "adapted-vectors.npz")
        or training["checkpoint_sha256"] != digest(RUN / "step-200.safetensors")
        or not completed["baseline_exact_counter_and_timeline_parity"]
    ):
        raise ValueError("Completed fixed comparison changed")
    with np.load(RUN / "adapted-vectors.npz", allow_pickle=False) as arrays:
        adapted = arrays["vectors"].copy()
    baseline = original[[row["source_index"] for row in manifest["rows"]]]
    if adapted.shape != baseline.shape or not np.isfinite(adapted).all():
        raise ValueError("Complete finite adapted vectors required")
    lookup = {row["source_index"]: i for i, row in enumerate(manifest["rows"])}
    bank = [lookup[i] for i in protocol["bank_source_indices"]]
    owners = np.array([manifest["rows"][i]["track_id"] + 1 for i in bank])
    panels = {}
    for name, values in (("untrained_bank", baseline), ("spatial_tail200", adapted)):
        result = completed["panels"][name]
        panels[name] = {
            key: value for key, value in result.items() if key != "timeline"
        }
        panels[name]["score_stages"] = stages(manifest, values, bank, owners, result)
        panels[name]["retrieval_distributions"] = describe(
            manifest, values, bank, owners, result
        )
    paths = [
        Path(__file__),
        FREEZE,
        ROOT / "recognition_spatial_tail_protocol.json",
        ROOT / "recognition_temporal_diagnosis.py",
        ROOT / "recognition_temporal_retrieval.py",
        ROOT / "results/2026-10-03/recognition/spatial-tail-prefix-parity.json",
        RUN / "training.json",
        RUN / "calibration.json",
        RUN / "step-200.safetensors",
        RUN / "adapted-vectors.npz",
    ]
    report = {
        "status": "COMPLETE_NEGATIVE_NO_PROMOTION",
        "files": {str(path): digest(path) for path in paths},
        "panels": panels,
        "all_goal_gates": completed["all_goal_gates"],
        "baseline_exact_counter_and_timeline_parity": True,
        "training": {key: value for key, value in training.items() if key != "steps"},
        "limits": completed["limits"],
        "scope": "All six initially anchored teacher lineages used for farm adaptation; this is neither automatic biological identification nor unseen-identity transfer. Same exposed450–629 panel, original96bank, fixed.65/.10/3 policy. No new model call, threshold search, alternate epoch, later query or3000+pixels.",
    }
    write_json(OUTPUT, report)
    print(json.dumps({name: panel["score_stages"] for name, panel in panels.items()}))


if __name__ == "__main__":
    main()
