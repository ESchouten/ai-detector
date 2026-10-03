from copy import deepcopy
from pathlib import Path

import pytest
from detection_birth_extended import full_prefix, unchanged_policy
from joint_readout_prefix import FIELDS


def values():
    rows = [dict.fromkeys((*FIELDS, "publisher_frame"), 0) for _ in range(3059)]
    for index, row in enumerate(rows):
        row.update(second=index / 2, mask_sha256="mask", sam_attempts=[])
    before = {
        "complete": True,
        "all_frames": rows,
        "quarantine_events": [{"second": 100, "kind": "quarantined"}],
    }
    after = deepcopy(before)
    after["all_frames"].append({"second": 1529.5})
    after["quarantine_events"].append({"second": 1700, "kind": "restored"})
    return before, after


def test_entire_closed_loop_prefix_is_compared(monkeypatch):
    monkeypatch.setattr("detection_birth_extended.digest", lambda path: "mask")
    before, after = values()
    result = full_prefix(before, after, (Path("old"), Path("new")))
    assert result["exact"]
    assert result["input_frames"] == 3059
    after["all_frames"][3000]["named_track_ids"] = [1]
    result = full_prefix(before, after, (Path("old"), Path("new")))
    assert not result["exact"]
    assert result["differences"] == [{"second": 1500, "fields": ["named_track_ids"]}]


def test_cache_paths_and_timings_do_not_change_decisions(monkeypatch):
    monkeypatch.setattr("detection_birth_extended.digest", lambda path: "mask")
    before, after = values()
    before["all_frames"][10]["sam_attempts"] = [
        {"accepted": True, "cache": "old", "batch_seconds": 2}
    ]
    after["all_frames"][10]["sam_attempts"] = [
        {"accepted": True, "cache": "new", "batch_seconds": 3}
    ]
    assert full_prefix(before, after, (Path("old"), Path("new")))["exact"]
    after["all_frames"][10]["sam_attempts"][0]["accepted"] = False
    assert not full_prefix(before, after, (Path("old"), Path("new")))["exact"]


def test_extended_scope_rejects_policy_changes():
    import json

    baseline = json.loads(
        Path(__file__)
        .with_name("detection_birth_joint_readout_protocol.json")
        .read_text()
    )
    extension = deepcopy(baseline)
    extension.update(
        last_processed_second=2999, comparison_windows=[[1800, 2099], [2700, 2999]]
    )
    unchanged_policy(extension, baseline)
    extension["naming"]["minimum_p10"] = 0.69
    with pytest.raises(ValueError, match="unchanged"):
        unchanged_policy(extension, baseline)
