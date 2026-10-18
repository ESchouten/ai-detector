from pathlib import Path

import pytest
from PIL import Image

from reid.manifest import (
    Crop,
    crops_from_pattern,
    is_grayscale,
    read_manifest,
    write_manifest,
)


def test_manifest_round_trip_keeps_paths_relative(tmp_path: Path):
    crops = (
        Crop(tmp_path / "a" / "1.jpg", "a", "2026-10-01", "cam1", "t1", True),
        Crop(tmp_path / "b" / "2.jpg", "b"),
    )
    manifest = tmp_path / "manifest.csv"

    write_manifest(manifest, crops)

    assert "a/1.jpg" in manifest.read_text()
    assert read_manifest(manifest) == crops


def test_manifest_requires_path_and_identity(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path,session\nx.jpg,1\n")

    with pytest.raises(ValueError, match="identity"):
        read_manifest(manifest)


def test_manifest_rejects_unknown_night_value(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path,identity,night\nx.jpg,a,dusk\n")

    with pytest.raises(ValueError, match=":2: night"):
        read_manifest(manifest)


def test_pattern_reads_identity_session_and_camera_from_paths(tmp_path: Path):
    for day, cow, camera in (
        ("2023Aug14", "024", 1),
        ("2023Aug15", "024", 2),
        ("2023Aug14", "031", 1),
    ):
        folder = tmp_path / day / cow
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4)).save(folder / f"00001_{camera}.jpg")
    (tmp_path / "2023Aug14" / "notes.txt").write_text("not a picture")

    crops = crops_from_pattern(
        tmp_path, r"(?P<session>\w+)/(?P<identity>\d+)/\d+_(?P<camera>\d)\.jpg$"
    )

    assert [(c.identity, c.session, c.camera) for c in crops] == [
        ("024", "2023Aug14", "1"),
        ("031", "2023Aug14", "1"),
        ("024", "2023Aug15", "2"),
    ]


def test_default_style_pattern_is_one_folder_per_animal(tmp_path: Path):
    for cow in ("17", "42"):
        (tmp_path / cow).mkdir()
        Image.new("RGB", (4, 4)).save(tmp_path / cow / "a.png")

    crops = crops_from_pattern(tmp_path, r"^(?P<identity>[^/]+)/")

    assert [crop.identity for crop in crops] == ["17", "42"]


def test_pattern_needs_an_identity_group(tmp_path: Path):
    with pytest.raises(ValueError, match="identity"):
        crops_from_pattern(tmp_path, r"(\d+)")


def test_night_is_a_picture_without_colour(tmp_path: Path):
    (tmp_path / "cow").mkdir()
    Image.new("RGB", (16, 16), (90, 90, 90)).save(tmp_path / "cow" / "ir.png")
    Image.new("RGB", (16, 16), (150, 60, 40)).save(tmp_path / "cow" / "day.png")

    crops = crops_from_pattern(
        tmp_path, r"^(?P<identity>[^/]+)/", night_from_colour=True
    )

    assert {crop.path.stem: crop.night for crop in crops} == {"day": False, "ir": True}
    assert is_grayscale(tmp_path / "cow" / "ir.png")
