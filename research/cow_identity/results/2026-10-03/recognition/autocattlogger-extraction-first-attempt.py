"""Inspect one pinned author artifact without executing its training metadata."""

from __future__ import annotations

import hashlib
import json
import pickletools
import zipfile
from pathlib import Path

import timm
import torch

CHECKPOINT_SHA = "a23cfd37a78a0745392e5b0457dd468e9afbea3eebbbf19b94d32b988734438f"
STATE_START = 12441
STATE_END = 295404
ALLOWED_GLOBALS = {
    "collections OrderedDict",
    "torch._utils _rebuild_tensor_v2",
    "torch FloatStorage",
    "torch LongStorage",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def storage_members(operations: list) -> dict[str, int]:
    """Read only this artifact's five-scalar persistent-storage tuples."""
    memo = {}
    members = {}
    for i, (operation, _, _) in enumerate(operations):
        if operation.name != "BINPERSID":
            continue
        assert operations[i - 1][0].name in {"BINPUT", "LONG_BINPUT"}
        assert operations[i - 2][0].name == "TUPLE"
        start = next(j for j in range(i - 3, -1, -1) if operations[j][0].name == "MARK")
        values = []
        for item, value, _ in operations[start + 1 : i - 2]:
            if item.name in {"BINUNICODE", "GLOBAL", "BININT1", "BININT2", "BININT"}:
                values.append(value)
            elif item.name in {"BINGET", "LONG_BINGET"}:
                values.append(memo[value])
            elif item.name in {"BINPUT", "LONG_BINPUT"}:
                memo[value] = values[-1]
            else:
                raise ValueError(f"Unexpected storage opcode: {item.name}")
        kind, storage, key, location, count = values
        assert kind == "storage" and location == "cpu"
        assert storage in {"torch FloatStorage", "torch LongStorage"}
        assert isinstance(key, str) and key.isdecimal() and key not in members
        assert isinstance(count, int) and 0 < count < 100_000_000
        members[key] = count * (4 if storage == "torch FloatStorage" else 8)
    assert len(members) == 1754 and sum(members.values()) < 300_000_000
    return members


def extract(source: Path, target: Path) -> dict:
    assert digest(source) == CHECKPOINT_SHA, (
        "This extractor accepts exactly one artifact"
    )
    with zipfile.ZipFile(source) as archive:
        raw = archive.read("archive/data.pkl")
        operations = list(pickletools.genops(raw))
        selected = [item for item in operations if STATE_START <= item[2] < STATE_END]
        assert (
            selected[0][0].name == "GLOBAL"
            and selected[0][1] == "collections OrderedDict"
        )
        assert selected[-1][0].name == "BUILD" and selected[-1][2] == STATE_END - 1
        assert (
            next(item for item in operations if item[2] == STATE_END)[1]
            == "message_hub"
        )
        globals_used = {value for item, value, _ in selected if item.name == "GLOBAL"}
        assert globals_used == ALLOWED_GLOBALS
        assert not any(
            item.name in {"STACK_GLOBAL", "EXT1", "EXT2", "EXT4", "STOP"}
            for item, _, _ in selected
        )
        defined = {
            value
            for item, value, _ in selected
            if item.name in {"BINPUT", "LONG_BINPUT"}
        }
        read = {
            value
            for item, value, _ in selected
            if item.name in {"BINGET", "LONG_BINGET"}
        }
        assert read - defined == {130}
        assert next(item for item in operations if item[2] == 11941)[:2] == (
            pickletools.code2op["X"],
            "",
        )
        assert next(item for item in operations if item[2] == 11946)[:2] == (
            pickletools.code2op["q"],
            130,
        )
        members = storage_members(selected)
        assert all(
            archive.getinfo(f"archive/data/{key}").file_size == size
            for key, size in members.items()
        )
        # Protocol 2, memoize the verified empty string at130, pop it; retain the
        # exact state_dict opcodes, then end the standalone OrderedDict pickle.
        new_pickle = (
            b"\x80\x02X\x00\x00\x00\x00q\x820" + raw[STATE_START:STATE_END] + b"."
        )
        assert list(pickletools.genops(new_pickle))[-1][0].name == "STOP"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr("archive/data.pkl", new_pickle)
            for name in ("archive/version", "archive/byteorder"):
                if name in archive.namelist():
                    output.writestr(name, archive.read(name))
            for key in members:
                name = f"archive/data/{key}"
                output.writestr(name, archive.read(name))
    assert torch.serialization.get_unsafe_globals_in_checkpoint(target) == []
    return {
        "source_sha256": CHECKPOINT_SHA,
        "state_slice": [STATE_START, STATE_END],
        "external_memo": {"130": ""},
        "globals": sorted(globals_used),
        "storage_count": len(members),
        "storage_bytes": sum(members.values()),
        "state_archive_sha256": digest(target),
    }


def topology(state: dict) -> dict:
    with torch.device("meta"):
        model = timm.create_model(
            "hrnet_w48",
            pretrained=False,
            features_only=True,
            feature_location="",
            out_indices=(1,),
        )
        head = torch.nn.Conv2d(48, 10, 1)
    removed = [
        key
        for key in model.state_dict()
        if key.startswith(tuple(f"stage4.2.fuse_layers.{n}." for n in (1, 2, 3)))
    ]
    assert len(removed) == 78
    model.stage4[2].fuse_layers = torch.nn.ModuleList([model.stage4[2].fuse_layers[0]])
    model.stage4[2].multi_scale_output = False
    backbone = {
        key.removeprefix("backbone."): value
        for key, value in state.items()
        if key.startswith("backbone.")
    }
    final = {
        key.removeprefix("head.final_layer."): value
        for key, value in state.items()
        if key.startswith("head.final_layer.")
    }
    assert len(backbone) == 1752 and set(final) == {"weight", "bias"}
    assert len(backbone) + len(final) == len(state)
    model.load_state_dict(backbone, strict=True, assign=True)
    head.load_state_dict(final, strict=True, assign=True)
    assert all(
        torch.equal(value, backbone[key]) for key, value in model.state_dict().items()
    )
    assert all(
        torch.equal(value, final[key]) for key, value in head.state_dict().items()
    )
    return {
        "timm": timm.__version__,
        "torch": torch.__version__,
        "strict_backbone_tensors": len(backbone),
        "strict_head_tensors": len(final),
        "removed_unused_final_output_tensors": removed,
        "head_shape": list(final["weight"].shape),
        "trainable_parameters": sum(x.numel() for x in model.parameters())
        + sum(x.numel() for x in head.parameters()),
        "forward_executed": False,
        "author_reference_equivalence": "NOT_TESTED",
    }


def main() -> None:
    directory = Path(".cache/cow-autocattlogger")
    source = directory / "epoch_210_kpDatasetV5_2024.pth"
    target = directory / "pose-state-only.pt"
    report = extract(source, target)
    state = torch.load(target, map_location="cpu", weights_only=True)
    assert isinstance(state, dict) and all(
        isinstance(value, torch.Tensor) for value in state.values()
    )
    report.update(topology(state))
    report["extractor_sha256"] = digest(Path(__file__))
    report["state_shapes"] = {key: list(value.shape) for key, value in state.items()}
    path = directory / "checkpoint-inspection.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"state_shapes", "removed_unused_final_output_tensors"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
