import json
from pathlib import Path

from PIL import Image

from conftest import FakeEmbedder, FakeMatcher
from reid.benchmark import Options, embeddings, evaluate
from reid.cli import _training_crops, main, table
from reid.manifest import read_manifest, write_manifest


def test_manifest_from_pattern_writes_a_manifest(tmp_path: Path):
    for cow in ("17", "42"):
        (tmp_path / "data" / cow).mkdir(parents=True)
        Image.new("RGB", (4, 4)).save(tmp_path / "data" / cow / "2026-10-01.jpg")

    main(
        [
            "manifest-from-pattern",
            str(tmp_path / "data"),
            "--out",
            str(tmp_path / "m.csv"),
        ]
    )

    assert (tmp_path / "m.csv").read_text().splitlines()[1:] == [
        "data/17/2026-10-01.jpg,17,,,,",
        "data/42/2026-10-01.jpg,42,,,,",
    ]


def test_report_prints_saved_results(herd, tmp_path: Path, capsys):
    result = evaluate(herd, embeddings(herd, FakeEmbedder()), Options())
    saved = tmp_path / "herd.fake.json"
    saved.write_text(json.dumps({"model": "fake", "manifest": "herd", **result}))

    main(["report", str(saved)])

    output = capsys.readouterr().out
    assert output.strip() == table([json.loads(saved.read_text())])
    assert "| fake | herd | crop | 100.0 |" in output
    assert "| fake | herd | track | 100.0 | – |" in output


def test_benchmark_scores_each_farm_at_the_other_farms_threshold(
    herd, tmp_path: Path, monkeypatch, capsys
):
    write_manifest(tmp_path / "north.csv", herd)
    write_manifest(tmp_path / "south.csv", herd[: len(herd) // 2])

    monkeypatch.setattr(
        "reid.backbones.build", lambda model, **options: FakeEmbedder(noise=0.1)
    )
    out = tmp_path / "results"

    main(
        [
            "benchmark",
            str(tmp_path / "north.csv"),
            str(tmp_path / "south.csv"),
            "--model",
            "fake",
            "--out",
            str(out),
        ]
    )

    north = json.loads((out / "north.fake.json").read_text())
    south = json.loads((out / "south.fake.json").read_text())
    assert north["thresholds"]["other_farms"] == south["thresholds"]["own"]
    assert south["thresholds"]["other_farms"] == north["thresholds"]["own"]
    assert "| fake | north |" in capsys.readouterr().out


def test_enroll_saves_the_simulation_and_prints_a_row_per_grouping(
    herd, tmp_path: Path, monkeypatch, capsys
):
    write_manifest(tmp_path / "farm.csv", herd)
    monkeypatch.setattr(
        "reid.backbones.build", lambda model, **options: FakeEmbedder(noise=0.1)
    )
    monkeypatch.setattr("reid.local.KeypointMatcher", lambda **options: FakeMatcher())
    out = tmp_path / "results"

    main(
        [
            "enroll",
            str(tmp_path / "farm.csv"),
            "--model",
            "fake",
            "--merge",
            "0.8",
            "0.9",
            "--goal",
            "1",
            "--coat",
            "0",
            "0.5",
            "--out",
            str(out),
        ]
    )

    saved = json.loads((out / "enrol-farm.fake.json").read_text())
    assert [(entry["merge"], entry["coat"]) for entry in saved["grouped"]] == [
        (0.8, 0.0),
        (0.8, 0.5),
        (0.9, 0.0),
        (0.9, 0.5),
    ]
    output = capsys.readouterr().out
    assert output.startswith("8 cows in 32 sightings while enrolling")
    assert (
        "| labelled | none | 0.0 | alone | – | – | – | – | – | 100.0 (100.0) "
        "| 100.0 | 100.0 | 0 |" in output
    )
    assert "| grouped at 0.8 | none | 0.0 | alone | 8 | 100.0 | 8 | 8 | 8 |" in output
    assert "| grouped at 0.8 | none | 0.5 | alone | 8 | 100.0 | 8 | 8 | 8 |" in output


def test_training_crops_keep_cows_of_different_farms_apart(herd, tmp_path: Path):
    write_manifest(tmp_path / "north.csv", herd)
    write_manifest(tmp_path / "south.csv", herd[:24])

    crops, farms = _training_crops(
        [tmp_path / "north.csv", tmp_path / "south.csv"], None, None, 0
    )

    assert len(crops) == len(herd) + 24
    assert farms.count("south") == 24
    assert crops[0].identity == "north/cow0"
    assert crops[-1].identity == "south/cow0"
    assert crops[-1].track.startswith("south/")
    single, _ = _training_crops([tmp_path / "north.csv"], "2026-10-03", None, 0)
    assert {crop.identity for crop in single} == {f"cow{n}" for n in range(8)}
    assert {crop.session for crop in single} == {"2026-10-01", "2026-10-02"}


def test_hide_copies_a_manifest_with_every_picture_partly_hidden(herd, tmp_path: Path):
    manifest = tmp_path / "herd.csv"
    write_manifest(manifest, herd)

    main(["hide", str(manifest), "--out", str(tmp_path / "hidden")])

    hidden = read_manifest(tmp_path / "hidden" / "manifest.csv")
    assert [crop.identity for crop in hidden] == [crop.identity for crop in herd]
    assert [crop.session for crop in hidden] == [crop.session for crop in herd]
    for original, copy in zip(herd, hidden, strict=True):
        assert copy.path.parent == tmp_path / "hidden"
        with Image.open(original.path) as before, Image.open(copy.path) as after:
            assert after.size == before.size
