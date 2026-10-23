import csv
import json
from pathlib import Path

from conftest import FakeEmbedder
from reid.benchmark import embeddings
from reid.cli import main
from reid.manifest import read_manifest, write_manifest
from reid.naming import apply_names, group_sightings, write_page


def test_each_cow_becomes_one_group_of_her_sightings(herd):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1))

    seen, groups = group_sightings(herd, vectors, merge=0.8)

    assert len(seen) == 64
    assert len(set(groups)) == 8
    for group in set(groups):
        cows = {herd[seen[s][0]].identity for s, g in enumerate(groups) if g == group}
        assert len(cows) == 1


def test_the_page_shows_a_spread_of_each_group_and_maps_every_crop(herd, tmp_path):
    vectors = embeddings(herd, FakeEmbedder(noise=0.1))
    seen, groups = group_sightings(herd, vectors, merge=0.8)
    out = tmp_path / "page"

    count = write_page(herd, seen, groups, out, per_group=3)

    assert count == 8
    page = (out / "index.html").read_text()
    cards = json.loads(page.split("const CARDS = ")[1].split(";\n")[0])
    assert [len(card["shown"]) for card in cards] == [3] * 8
    assert [len(card["hidden"]) for card in cards] == [5] * 8
    first = cards[0]["shown"]
    assert [s["session"] for s in first] == ["2026-10-01", "2026-10-03", "2026-10-04"]
    assert len(list((out / "thumbs").iterdir())) == 24
    with (out / "groups.csv").open() as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == len(herd)
    assert {row["group"] for row in rows} == {str(n) for n in range(1, 9)}


def test_named_sightings_become_a_manifest_and_the_rest_are_dropped(herd, tmp_path):
    groups = tmp_path / "groups.csv"
    with groups.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("path", "sighting", "group"))
        for index, crop in enumerate(herd[:9]):
            writer.writerow((crop.path.resolve().as_posix(), index // 3, 1))
    names = tmp_path / "names.csv"
    names.write_text('sighting,name\n0,"412"\n2," 87 "\n1,\n')

    named = apply_names(herd, groups, names)

    assert [crop.identity for crop in named] == ["412"] * 3 + ["87"] * 3
    assert [crop.path for crop in named] == [c.path for c in herd[:3] + herd[6:9]]


def test_groups_and_apply_names_from_the_command_line(
    herd, tmp_path: Path, monkeypatch, capsys
):
    write_manifest(tmp_path / "farm.csv", herd)
    monkeypatch.setattr(
        "reid.backbones.build", lambda model, **options: FakeEmbedder(noise=0.1)
    )
    out = tmp_path / "page"

    main(
        [
            "groups",
            str(tmp_path / "farm.csv"),
            "--model",
            "fake",
            "--merge",
            "0.8",
            "--out",
            str(out),
        ]
    )

    assert "64 sightings in 8 groups" in capsys.readouterr().out
    (out / "names.csv").write_text("sighting,name\n0,412\n")
    main(
        [
            "apply-names",
            str(tmp_path / "farm.csv"),
            str(out / "groups.csv"),
            str(out / "names.csv"),
            "--out",
            str(tmp_path / "named.csv"),
        ]
    )
    named = read_manifest(tmp_path / "named.csv")
    assert [crop.identity for crop in named] == ["412"] * 3
