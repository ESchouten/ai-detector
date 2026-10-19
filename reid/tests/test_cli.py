import json
from pathlib import Path

from PIL import Image

from conftest import FakeEmbedder
from reid.benchmark import Options, embeddings, evaluate
from reid.cli import _training_crops, main, table
from reid.manifest import write_manifest


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
