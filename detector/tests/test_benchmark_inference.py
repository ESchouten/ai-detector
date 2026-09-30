import json
from datetime import datetime

import cv2
import numpy as np
import pytest

from aidetector.domain.models import Frame
from tests.support.onnx_model import write_detection_model
from tools.benchmark_inference import batch_sources, load_frames, main, parse_args


def test_shape_grouping_preserves_every_source_and_never_reaches_into_a_future_batch():
    frames = {
        str(i): (Frame(datetime.now(), np.zeros(shape, dtype=np.uint8)),)
        for i, shape in enumerate([(32, 64, 3), (64, 64, 3), (32, 64, 3)] * 2)
    }
    assert batch_sources(frames, 3, grouped=False) == [("0", "1", "2"), ("3", "4", "5")]
    assert batch_sources(frames, 3, grouped=True) == [
        ("0", "2"),
        ("1",),
        ("3", "5"),
        ("4",),
    ]


def test_corrupt_benchmark_image_fails_instead_of_skipping_it(tmp_path):
    path = tmp_path / "invalid.jpg"
    path.write_text("not an image")
    with pytest.raises(ValueError, match="Cannot read image"):
        load_frames([path], 1280)


@pytest.mark.parametrize("argument", ["--batch", "--warmup", "--iterations"])
def test_benchmark_requires_positive_counts(argument):
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--models",
                "x.pt",
                "--images",
                "x.jpg",
                "--output",
                "report",
                argument,
                "0",
            ]
        )


def test_real_benchmark_reports_timings_shapes_predictions_and_sdk_validation(
    tmp_path,
    monkeypatch,
):
    # Plotting is disabled; don't let SDK dataset validation fetch a font.
    monkeypatch.setattr("ultralytics.data.utils.check_font", lambda *args: None)
    model = tmp_path / "model.onnx"
    write_detection_model(model)
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    labels = tmp_path / "labels"
    labels.mkdir()
    images = []
    for index, shape in enumerate([(32, 64, 3), (64, 64, 3), (32, 64, 3)]):
        path = image_dir / f"{index}.png"
        cv2.imwrite(str(path), np.full(shape, 100, dtype=np.uint8))
        (labels / f"{index}.txt").write_text("0 0.4 0.5 0.4 0.5\n")
        images.append(str(path))
    data = tmp_path / "data.yaml"
    data.write_text(
        f"path: {tmp_path.as_posix()}\ntrain: images\nval: images\nnames: {{0: cow}}\n"
    )
    preset = tmp_path / "preset.json"
    preset.write_text(
        json.dumps(
            {
                "yolo": {"model": "unused.pt", "imgsz": 64, "confidence": {"cow": 0.5}},
                "detection": {"frames_width": 64},
            }
        )
    )
    output = tmp_path / "report"
    main(
        [
            "--models",
            str(model),
            "--images",
            *images,
            "--preset",
            str(preset),
            "--device",
            "cpu",
            "--batch",
            "3",
            "--warmup",
            "1",
            "--iterations",
            "2",
            "--data",
            str(data),
            "--output",
            str(output),
        ],
    )
    report = json.loads((output / "report.json").read_text())
    assert report["settings"]["imgsz"] == report["frames_width"] == 64
    assert report["preparation"]["file_read_ms"] > 0
    result = report["models"][0]
    assert result["backend"] == {"format": "onnx", "device": "cpu", "fp16": False}
    assert result["arrival_order"]["batches"] == [["0", "1", "2"]]
    assert result["same_shape"]["batches"] == [["0", "2"], ["1"]]
    for mode in ("arrival_order", "same_shape"):
        measurement = result[mode]
        assert measurement["pass_ms_p95"] >= measurement["pass_ms_p50"] > 0
        assert measurement["images_per_second"] > 0
        assert measurement["sdk_ms_per_image"]["inference"] > 0
        assert set(measurement["predictions"]) == {"0", "1", "2"}
        assert all(len(boxes) == 1 for boxes in measurement["predictions"].values())
        assert all(
            box["label"] == "cow"
            for boxes in measurement["predictions"].values()
            for box in boxes
        )
    assert "metrics/mAP50(B)" in result["validation"]["metrics"]
    assert result["validation"]["per_class"][0]["Class"] == "cow"
