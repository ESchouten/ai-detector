import json
from pathlib import Path

from PIL import Image

from conftest import FakeEmbedder
from reid.benchmark import Options, embeddings, evaluate
from reid.cli import main, table


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
    assert "| fake | herd | 100.0 |" in output
