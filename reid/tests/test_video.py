from pathlib import Path

import numpy as np
import pytest

from reid.cli import main
from reid.manifest import read_manifest

cv2 = pytest.importorskip("cv2")


def _video(path: Path, frames: int) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for _ in range(frames):
        image = np.zeros((240, 320, 3), np.uint8)
        image[40:140, 20:140] = (0, 0, 255)
        writer.write(image)
    writer.release()


def test_labelled_video_gives_tracked_crops(tmp_path: Path):
    video = tmp_path / "video1.avi"
    _video(video, 40)
    labels = tmp_path / "labels"
    labels.mkdir()
    for frame in range(40):
        lines = []
        if frame < 10 or frame >= 30:  # cow 7 leaves for a while and returns
            lines.append("7 0.25 0.375 0.375 0.4167")
        lines.append("9 0.98 0.5 0.1 0.9")  # cut by the picture's edge
        (labels / f"frame{frame:05d}.txt").write_text("\n".join(lines) + "\n")
    manifest = tmp_path / "manifest.csv"

    main(
        [
            "crops-from-video",
            str(video),
            str(labels),
            "--out",
            str(tmp_path / "crops"),
            "--manifest",
            str(manifest),
            "--session",
            "2023-08-25",
            "--every",
            "5",
            "--min-size",
            "20",
            "--identity-prefix",
            "cow_",
        ]
    )

    crops = read_manifest(manifest)
    assert {crop.identity for crop in crops} == {"cow_7"}
    assert len(crops) == 4  # frames 0, 5, 30 and 35
    assert len({crop.track for crop in crops}) == 2
    assert all(crop.session == "2023-08-25" for crop in crops)
    assert (tmp_path / "crops" / "video1-preview.jpg").exists()
    first = cv2.imread(str(crops[0].path))
    assert first.shape[:2] == (100, 120)
    assert first[..., 2].mean() > 200


def test_append_keeps_earlier_crops(tmp_path: Path):
    video = tmp_path / "v.avi"
    _video(video, 10)
    labels = tmp_path / "labels"
    labels.mkdir()
    for frame in range(10):
        (labels / f"{frame}.txt").write_text("3 0.25 0.375 0.375 0.4167\n")
    manifest = tmp_path / "manifest.csv"
    common = [
        "--out",
        str(tmp_path / "crops"),
        "--manifest",
        str(manifest),
        "--every",
        "5",
        "--min-size",
        "20",
    ]

    main(["crops-from-video", str(video), str(labels), "--session", "d1", *common])
    main(
        [
            "crops-from-video",
            str(video),
            str(labels),
            "--session",
            "d2",
            "--append",
            *common,
        ]
    )

    assert [crop.session for crop in read_manifest(manifest)] == [
        "d1",
        "d1",
        "d2",
        "d2",
    ]
