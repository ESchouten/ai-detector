import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aidetector.configuration import (
    Config,
    ConfigurationError,
    DetectorConfig,
    DiskConfig,
    ExportersConfig,
    HealthcheckConfig,
    SourceConfig,
    TelegramConfig,
    VLMConfig,
    WebhookConfig,
    YoloConfig,
    load_config,
    source_kind,
)


def test_current_example_config_is_supported():
    path = Path(__file__).resolve().parents[2] / "example/config.json"
    config = load_config(path)
    detector = config.detectors[0]
    assert detector.detection.source == ("sprong24.mp4",)
    assert len(detector.vlm) == 1
    assert len(detector.exporters.disk) == 1
    assert len(detector.exporters.telegram) == 1


def test_scalar_and_list_representations_normalize_at_boundary():
    one = DetectorConfig.model_validate(
        {
            "detection": {"source": "0"},
            "vlm": {"model": "provider/model", "prompt": "Detect?"},
            "exporters": {"disk": {}, "webhook": {"url": "https://example.test"}},
        }
    )
    many = DetectorConfig.model_validate(
        {
            "detection": {"source": ["0"]},
            "vlm": [{"model": ["provider/model"], "prompt": "Detect?"}],
            "exporters": {"disk": [{}], "webhook": [{"url": "https://example.test"}]},
        }
    )
    assert one == many
    assert one.vlm[0].model == ("provider/model",)


def test_explicit_models_can_be_composed_without_json_conversion():
    detector = DetectorConfig(
        detection=SourceConfig(source=("0",)),
        vlm=VLMConfig(model=("model",), prompt="Detect?"),
        exporters=ExportersConfig(
            disk=DiskConfig(),
            telegram=TelegramConfig(token="secret", chat="chat"),
            webhook=WebhookConfig(url="https://example.test"),
        ),
    )
    assert len(detector.exporters.telegram) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"frames_min": 0},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": {"cow": float("nan")}},
        {"confidence": {}},
        {"cooldown": -1},
        {"cooldown": {}},
        {"time_max": 0},
        {"timeout": -1},
        {"strategy": "LATEST"},
    ],
)
def test_invalid_yolo_settings_fail_at_input_boundary(overrides):
    with pytest.raises(ValidationError):
        YoloConfig.model_validate({"model": "model.pt", **overrides})


@pytest.mark.parametrize("source", [[], "", "  ", ["camera", "camera"], None])
def test_invalid_sources_are_rejected(source):
    with pytest.raises(ValidationError):
        SourceConfig.model_validate({"source": source})


@pytest.mark.parametrize(
    "source, kind",
    [
        ("0", "stream"),
        ("rtsps://camera/live.mp4", "stream"),
        ("tcp://camera:8000", "stream"),
        ("udp://camera:8000", "stream"),
        ("HTTPS://camera/live", "stream"),
        ("https://camera/video.MP4?token=fake#clip", "video"),
        ("video.mp4", "video"),
        (r"C:\recordings\video.mp4", "video"),
        ("camera#1.png", "image"),
        ("camera?1.png", "image"),
        ("image.JPG", "image"),
    ],
)
def test_supported_source_syntax_has_one_classification(source, kind):
    config = SourceConfig(source=(source,))
    assert config.source == (source,)
    assert source_kind(config.source[0]) == kind


def test_source_groups_are_validated_before_startup():
    with pytest.raises(ValidationError, match="separate detector definitions"):
        SourceConfig(source=("video.mp4", "0"))
    assert SourceConfig(source=("image.png", "video.mp4")).source == (
        "image.png",
        "video.mp4",
    )


def test_malformed_source_url_error_does_not_echo_credentials(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {"detectors": [{"detection": {"source": "rtsp://private-secret@[bad"}}]}
        )
    )
    with pytest.raises(ConfigurationError, match="Source URL is invalid") as error:
        load_config(path)
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize("model", [WebhookConfig, HealthcheckConfig])
@pytest.mark.parametrize(
    "url",
    [
        "https://private:secret@",
        "http://:8080",
        "https://host:invalid",
        "https://host:65536",
        "https://camera with spaces/",
        "http:camera",
        "http:/camera",
        "ftp://camera/",
    ],
)
def test_http_destinations_reject_invalid_urls(model, url):
    with pytest.raises(ValidationError):
        model(url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:80",
        "https://[::1]:8080/health",
        "HTTPS://user:token@host:8080/path?signature=a%2Fb#fragment",
    ],
)
def test_valid_http_destination_urls_are_preserved(url):
    assert HealthcheckConfig(url=url).url == url


def test_malformed_http_url_error_does_not_echo_url_contents(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "detectors": [{"detection": {"source": "0"}}],
                "health": {"url": "https://[private-secret]"},
            }
        )
    )
    with pytest.raises(ConfigurationError) as error:
        load_config(path)
    assert "private-secret" not in str(error.value)


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
def test_disk_directory_requires_one_category_name(directory):
    with pytest.raises(ValidationError):
        DiskConfig.model_validate({"directory": directory})


@pytest.mark.parametrize(
    "directory", [None, "mounts", "Camera 1", "animals.v2", ".hidden"]
)
def test_single_disk_category_names_are_preserved(directory):
    config = DiskConfig.model_validate({"directory": directory})
    assert config.model_dump(mode="json")["directory"] == directory


def test_config_loading_is_read_only(tmp_path):
    path = tmp_path / "config.json"
    content = '{ "detectors": [{ "detection": {"source": "video.mp4"} }] }\n'
    path.write_text(content)
    before = path.stat().st_mtime_ns
    config = load_config(path)
    assert config.detectors[0].detection.source == ("video.mp4",)
    assert path.read_text() == content
    assert path.stat().st_mtime_ns == before


def test_missing_config_is_not_created(tmp_path):
    path = tmp_path / "missing.json"
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(path)
    assert not path.exists()


def test_invalid_config_is_not_replaced_or_echoed(tmp_path):
    path = tmp_path / "config.json"
    content = json.dumps({"detectors": [], "secret": "private-token"})
    path.write_text(content)
    with pytest.raises(ConfigurationError) as raised:
        load_config(path)
    assert "private-token" not in str(raised.value)
    assert path.read_text() == content


def test_defaults_are_deterministic_and_secrets_do_not_appear_in_repr():
    assert YoloConfig(model="model.pt").frames_min == 3
    assert "private-token" not in repr(
        TelegramConfig(token="private-token", chat="chat")
    )
    assert "private-key" not in repr(
        VLMConfig(model=("model",), prompt="Detect?", key="private-key")
    )
    assert "camera-password" not in repr(
        SourceConfig(source=("rtsp://user:camera-password@camera",))
    )


def test_schema_describes_legacy_inputs_and_has_no_hardware_side_effects():
    schema = Config.model_json_schema()
    source = schema["$defs"]["SourceConfig"]["properties"]["source"]
    assert {item["type"] for item in source["anyOf"]} == {"string", "array"}
    assert schema["$defs"]["YoloConfig"]["properties"]["frames_min"]["default"] == 3


def test_invalid_file_encoding_is_a_config_error_without_exposing_contents(tmp_path):
    path = tmp_path / "config.json"
    original = b'{"key": "private-secret-\xff"}'
    path.write_bytes(original)
    with pytest.raises(ConfigurationError, match="must use UTF-8") as error:
        load_config(path)
    assert "private-secret" not in str(error.value)
    assert path.read_bytes() == original
