"""Validate external configuration without loading files or inspecting hardware."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

Probability = Annotated[float, Field(ge=0, le=1)]
Duration = Annotated[float, Field(ge=0)]
PositiveDuration = Annotated[float, Field(gt=0)]
PaddingRatio = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonEmptyString = Annotated[str, Field(min_length=1, pattern=r"\S")]
StringList = Annotated[list[NonEmptyString], Field(min_length=1)]
SourceList = Annotated[
    list[NonEmptyString], Field(min_length=1, json_schema_extra={"uniqueItems": True})
]
ProbabilityMap = Annotated[dict[NonEmptyString, Probability], Field(min_length=1)]
DurationMap = Annotated[dict[NonEmptyString, Duration], Field(min_length=1)]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
_HTTP_URL = TypeAdapter(AnyHttpUrl)


SourceKind = Literal["image", "video", "stream"]
_MEDIA_KINDS: dict[str, SourceKind] = {
    **dict.fromkeys(
        (".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"), "image"
    ),
    **dict.fromkeys(
        (
            ".avi",
            ".m4v",
            ".mkv",
            ".mov",
            ".mp4",
            ".mpeg",
            ".mpg",
            ".mts",
            ".ts",
            ".webm",
            ".wmv",
        ),
        "video",
    ),
}


def source_kind(source: str) -> SourceKind:
    """Classify supported source syntax without opening files or network connections."""
    if source.isdecimal():
        return "stream"
    if "://" not in source:
        kind = _MEDIA_KINDS.get(Path(source).suffix.lower())
        if kind is None:
            raise ValueError(
                "Use an image/video path, camera index, or supported stream URL"
            )
        return kind
    try:
        url = urlsplit(source)
    except ValueError:
        raise ValueError("Source URL is invalid") from None
    if url.scheme not in {"rtsp", "rtsps", "http", "https", "tcp", "udp"}:
        raise ValueError("Unsupported source URL; use RTSP, HTTP(S), TCP, or UDP")
    if not url.hostname:
        raise ValueError("Source URL needs a host")
    if url.scheme not in {"http", "https"}:
        return "stream"
    kind = _MEDIA_KINDS.get(Path(url.path).suffix.lower(), "stream")
    if kind == "image":
        raise ValueError("HTTP image sources are not supported; use a local image file")
    return kind


def _sequence(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    return value


class _ConfigModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True
    )


class YoloConfig(_ConfigModel):
    model: NonEmptyString
    task: Literal["detect", "segment"] = "detect"
    confidence: Probability | ProbabilityMap = 0
    tracking: bool = False
    time_max: PositiveDuration = 60
    timeout: Duration = 5
    cooldown: Duration | DurationMap = 0
    include_trailing_time: Duration = 1
    frames_min: PositiveInt = 3
    imgsz: PositiveInt = 640
    iou: Probability | None = None
    tracker: Literal["botsort.yaml", "bytetrack.yaml"] | None = None


class SourceConfig(_ConfigModel):
    source: Annotated[tuple[NonEmptyString, ...], Field(min_length=1, repr=False)]
    interval: Duration = 0
    frame_retention: PositiveInt = 15
    frames_width: Annotated[int, Field(ge=2)] = 1280

    @field_validator(
        "source", mode="before", json_schema_input_type=NonEmptyString | SourceList
    )
    @classmethod
    def normalize_sources(cls, value: object) -> object:
        return _sequence(value)

    @field_validator("source")
    @classmethod
    def validate_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        sources = tuple(source.strip() for source in value)
        if len(set(sources)) != len(sources):
            raise ValueError("Sources must be unique within a detector")
        kinds = {source_kind(source) for source in sources}
        if "stream" in kinds and len(kinds) > 1:
            raise ValueError(
                "Put finite files and live streams in separate detector definitions"
            )
        return sources


class VLMConfig(_ConfigModel):
    prompt: NonEmptyString
    model: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]
    key: str | None = Field(default=None, repr=False)
    url: str | None = Field(default=None, repr=False)
    strategy: Literal["IMAGE", "VIDEO"] = "VIDEO"
    crop_padding: PaddingRatio = 0.1
    timeout: PositiveDuration = 30
    attempts: PositiveInt = 3

    @field_validator(
        "model", mode="before", json_schema_input_type=NonEmptyString | StringList
    )
    @classmethod
    def normalize_models(cls, value: object) -> object:
        return _sequence(value)


class ExporterConfig(_ConfigModel):
    confidence: Probability | ProbabilityMap | None = None
    crop_padding: PaddingRatio = 0.1
    export_rejected: bool = False


class HttpConfig(_ConfigModel):
    url: NonEmptyString = Field(repr=False)
    method: HttpMethod = "GET"
    timeout: PositiveDuration = 30
    headers: dict[str, str] | None = Field(default=None, repr=False)
    body: str | None = Field(default=None, repr=False)

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        try:
            _HTTP_URL.validate_python(value, strict=True)
        except ValidationError:
            raise ValueError("HTTP destination URL is invalid") from None
        return value


class MediaConfig(ExporterConfig):
    include_image: bool = False
    include_plot: bool = False
    include_crop: bool = False
    include_video: bool = False
    video_width: Annotated[int, Field(ge=2)] | None = 1280
    video_crf: Annotated[int, Field(ge=0, le=51)] = 28


class TelegramConfig(MediaConfig):
    token: NonEmptyString = Field(repr=False)
    chat: NonEmptyString
    alert_every: PositiveInt = 1
    include_video: bool = True
    timeout: PositiveDuration = 30


class WebhookConfig(MediaConfig, HttpConfig):
    method: HttpMethod = "POST"
    token: str | None = Field(default=None, repr=False)
    data_type: Literal["binary", "base64", "none"] = "binary"
    data_max: PositiveInt | None = None
    include_crop: bool = True


class DiskConfig(ExporterConfig):
    directory: str | None = Field(
        default=None,
        pattern=r"^[^/\\:]*[^./\\:\s][^/\\:]*$",
        description="Single category directory name under detections/.",
    )
    strategy: Literal["ALL", "BEST"] = "BEST"
    export_rejected: bool = True


class ExportersConfig(_ConfigModel):
    disk: tuple[DiskConfig, ...] = ()
    telegram: tuple[TelegramConfig, ...] = ()
    webhook: tuple[WebhookConfig, ...] = ()

    @field_validator(
        "disk",
        mode="before",
        json_schema_input_type=DiskConfig | list[DiskConfig] | None,
    )
    @classmethod
    def normalize_disk(cls, value: object) -> object:
        return [value] if isinstance(value, DiskConfig) else _sequence(value)

    @field_validator(
        "telegram",
        mode="before",
        json_schema_input_type=TelegramConfig | list[TelegramConfig] | None,
    )
    @classmethod
    def normalize_telegram(cls, value: object) -> object:
        return [value] if isinstance(value, TelegramConfig) else _sequence(value)

    @field_validator(
        "webhook",
        mode="before",
        json_schema_input_type=WebhookConfig | list[WebhookConfig] | None,
    )
    @classmethod
    def normalize_webhook(cls, value: object) -> object:
        return [value] if isinstance(value, WebhookConfig) else _sequence(value)


class HealthcheckConfig(HttpConfig):
    interval: PositiveDuration = 60
    timeout: PositiveDuration = 5


class DetectorConfig(_ConfigModel):
    detection: SourceConfig
    yolo: YoloConfig | None = None
    vlm: tuple[VLMConfig, ...] = ()
    exporters: ExportersConfig = Field(default_factory=ExportersConfig)
    pending_events: PositiveInt = 8

    @field_validator(
        "vlm", mode="before", json_schema_input_type=VLMConfig | list[VLMConfig] | None
    )
    @classmethod
    def normalize_vlm(cls, value: object) -> object:
        return [value] if isinstance(value, VLMConfig) else _sequence(value)

    @field_validator(
        "exporters", mode="before", json_schema_input_type=ExportersConfig | None
    )
    @classmethod
    def normalize_exporters(cls, value: object) -> object:
        return {} if value is None else value


class OnnxConfig(_ConfigModel):
    provider: NonEmptyString | None = None
    winml: bool = True
    opset: PositiveInt = 20


class Config(_ConfigModel):
    schema_url: str | None = Field(default=None, alias="$schema")
    detectors: Annotated[tuple[DetectorConfig, ...], Field(min_length=1)]
    onnx: OnnxConfig = Field(default_factory=OnnxConfig)
    health: HealthcheckConfig | None = None


class ConfigurationError(ValueError):
    """User-actionable config error, without credentials or raw input in the message."""


def load_config(path: Path) -> Config:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration not found: {path}") from error
    except OSError as error:
        raise ConfigurationError(f"Cannot read configuration: {path}") from error
    except UnicodeError as error:
        raise ConfigurationError(f"Configuration must use UTF-8: {path}") from error
    try:
        return Config.model_validate_json(content)
    except ValidationError as error:
        details = "\n".join(
            f"  {'.'.join(map(str, item['loc'])) or 'document'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise ConfigurationError(
            f"Invalid configuration in {path}:\n{details}"
        ) from error
