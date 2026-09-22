import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aidetector.cli import initial_config
from aidetector.configuration import Config
from aidetector.schema import schemas

ROOT = Path(__file__).resolve().parents[2]


def test_schema_validates_example_and_offline_template():
    schema = schemas()["config.schema.json"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for document in (
        initial_config(),
        json.loads((ROOT / "example/config.json").read_text()),
    ):
        validator.validate(document)
        Config.model_validate(document)


@pytest.mark.parametrize("source", [[], "", " ", ["camera", "camera"]])
def test_schema_rejects_invalid_sources_at_the_external_boundary(source):
    validator = Draft202012Validator(schemas()["config.schema.json"])
    with pytest.raises(ValidationError):
        validator.validate({"detectors": [{"detection": {"source": source}}]})


@pytest.mark.parametrize(
    "directory",
    [
        "",
        " ",
        ".",
        "..",
        "/absolute",
        "nested/category",
        r"nested\category",
        "C:category",
    ],
)
def test_schema_rejects_disk_paths_that_break_archive_discovery(directory):
    validator = Draft202012Validator(schemas()["config.schema.json"])
    with pytest.raises(ValidationError):
        validator.validate(
            {
                "detectors": [
                    {
                        "detection": {"source": "video.mp4"},
                        "exporters": {"disk": {"directory": directory}},
                    }
                ]
            }
        )


def test_schema_describes_real_event_metadata_and_accepts_existing_records():
    schema = schemas()["metadata.schema.json"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(
        {
            "timestamp": "2026-01-01T12-00-00",
            "validated": True,
            "confidence": 0.9,
            "confidences": {"cow": 0.9},
            "detections": 3,
            "start": "2026-01-01T12:00:00",
            "end": "2026-01-01T12:00:01",
            "duration": 1,
            "crop": {"x1": 10, "y1": 10, "x2": 40, "y2": 40},
        }
    )
    with pytest.raises(ValidationError):
        validator.validate({"unrelated_provider_metadata": "value"})


def test_committed_schemas_match_their_authoritative_python_models():
    for filename, schema in schemas().items():
        assert json.loads((ROOT / "config" / filename).read_text()) == schema
