"""Validate external configuration without loading files or inspecting hardware."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    UrlConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

Probability = Annotated[float, Field(ge=0, le=1)]
Duration = Annotated[float, Field(ge=0)]
PositiveDuration = Annotated[float, Field(gt=0)]
PaddingRatio = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonEmptyString = Annotated[str, Field(min_length=1, pattern=r"\S")]
ClockTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
SourceList = Annotated[
    list[NonEmptyString], Field(min_length=1, json_schema_extra={"uniqueItems": True})
]
ProbabilityMap = Annotated[dict[NonEmptyString, Probability], Field(min_length=1)]
DurationMap = Annotated[dict[NonEmptyString, Duration], Field(min_length=1)]
# Two numbers, written so that the schema gives both coordinates a type.
Point = Annotated[tuple[Probability, ...], Field(min_length=2, max_length=2)]
Area = Annotated[
    tuple[Point, ...],
    Field(
        min_length=3,
        description="Polygon corners as x, y fractions of the picture's width and height.",
    ),
]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
_HTTP_URL = TypeAdapter(AnyHttpUrl)
_SOURCE_URL = TypeAdapter(
    Annotated[
        AnyUrl,
        UrlConstraints(
            allowed_schemes=["rtsp", "rtsps", "http", "https", "tcp", "udp"],
            host_required=True,
        ),
    ]
)


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
        url = _SOURCE_URL.validate_python(source, strict=True)
    except ValidationError:
        raise ValueError(
            "Source URL is invalid; use RTSP, HTTP(S), TCP, or UDP with a valid host and port"
        ) from None
    if url.scheme not in {"http", "https"}:
        return "stream"
    kind = _MEDIA_KINDS.get(Path(url.path or "").suffix.lower(), "stream")
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

    @property
    def outlines_tracks(self) -> bool:
        """Follows objects and outlines them, as recognising individuals needs."""
        return self.tracking and self.task == "segment"


class SourceConfig(_ConfigModel):
    source: Annotated[tuple[NonEmptyString, ...], Field(min_length=1, repr=False)]
    interval: Duration = 0
    frame_retention: PositiveInt = 15
    frames_width: Annotated[int, Field(ge=2)] = 1280
    areas: dict[NonEmptyString, Area] = Field(
        default_factory=dict,
        repr=False,
        description="Per source, the area a detection's box centre must lie in to count.",
    )

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

    @model_validator(mode="after")
    def areas_of_sources(self) -> SourceConfig:
        if not set(self.areas) <= set(self.source):
            raise ValueError("An area must belong to one of the detector's sources")
        return self


class VLMConfig(_ConfigModel):
    model_config = ConfigDict(
        json_schema_extra={
            "if": {
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
            "then": {
                "required": ["model"],
                "properties": {
                    "model": {
                        "anyOf": [
                            {"type": "string", "minLength": 1},
                            {"type": "array", "minItems": 1},
                        ]
                    }
                },
            },
        }
    )

    prompt: NonEmptyString
    model: tuple[NonEmptyString, ...] = ()
    key: str | None = Field(default=None, repr=False)
    url: str | None = Field(default=None, repr=False)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    strategy: Literal["IMAGE", "VIDEO"] = "VIDEO"
    crop_padding: PaddingRatio = 0.1
    timeout: PositiveDuration = 30
    attempts: PositiveInt = 3

    @field_validator(
        "model",
        mode="before",
        json_schema_input_type=NonEmptyString | list[NonEmptyString],
    )
    @classmethod
    def normalize_models(cls, value: object) -> object:
        return _sequence(value)

    @model_validator(mode="after")
    def connected_model(self) -> VLMConfig:
        if self.key is not None and not self.model:
            raise ValueError("Connected verification requires a model")
        return self


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


class QuietHours(_ConfigModel):
    """A daily period, in this computer's local time; it may run past midnight."""

    start: ClockTime
    end: ClockTime


class TelegramConfig(MediaConfig):
    token: NonEmptyString = Field(repr=False)
    chat: NonEmptyString
    alert_every: PositiveInt = 1
    quiet: QuietHours | None = Field(
        default=None, description="Alerts in this period arrive without sound."
    )
    include_video: bool = True
    timeout: PositiveDuration = 30


class WebhookConfig(MediaConfig, HttpConfig):
    method: HttpMethod = "POST"
    token: str | None = Field(default=None, repr=False)
    data_type: Literal["binary", "base64", "none", "file"] = Field(
        default="binary",
        description=(
            "binary: form fields and files; base64: JSON; none: no content; file: the "
            "first chosen picture or video as the whole body, or `body` without one."
        ),
    )
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
        return _sequence(value)

    @field_validator(
        "telegram",
        mode="before",
        json_schema_input_type=TelegramConfig | list[TelegramConfig] | None,
    )
    @classmethod
    def normalize_telegram(cls, value: object) -> object:
        return _sequence(value)

    @field_validator(
        "webhook",
        mode="before",
        json_schema_input_type=WebhookConfig | list[WebhookConfig] | None,
    )
    @classmethod
    def normalize_webhook(cls, value: object) -> object:
        return _sequence(value)


class HealthcheckConfig(HttpConfig):
    interval: PositiveDuration = 60
    timeout: PositiveDuration = 5


class DetectorConfig(_ConfigModel):
    detection: SourceConfig
    yolo: YoloConfig | None = None
    vlm: tuple[VLMConfig, ...] = ()
    exporters: ExportersConfig = Field(default_factory=ExportersConfig)

    @property
    def active_vlm(self) -> tuple[VLMConfig, ...]:
        return tuple(verifier for verifier in self.vlm if verifier.key is not None)

    @field_validator(
        "vlm", mode="before", json_schema_input_type=VLMConfig | list[VLMConfig] | None
    )
    @classmethod
    def normalize_vlm(cls, value: object) -> object:
        return _sequence(value)

    @field_validator(
        "exporters", mode="before", json_schema_input_type=ExportersConfig | None
    )
    @classmethod
    def normalize_exporters(cls, value: object) -> object:
        return {} if value is None else value


def _onnx_file(value: str) -> str:
    url = urlsplit(value)
    path = url.path if url.scheme in {"http", "https"} else value
    if Path(path).suffix.lower() != ".onnx":
        raise ValueError("A model for recognising individuals must be an ONNX file")
    return value


OnnxFile = Annotated[NonEmptyString, AfterValidator(_onnx_file)]


class CoatConfig(_ConfigModel):
    """Compare the coat details of a track and the individuals it resembles most."""

    keypoints: OnnxFile = Field(
        description="ONNX model that finds a picture's keypoints, as a path or an "
        "http(s) URL ending in .onnx."
    )
    matcher: OnnxFile = Field(
        description="ONNX model that matches two pictures' keypoints, as a path or "
        "an http(s) URL ending in .onnx."
    )


class TagsConfig(_ConfigModel):
    """Read the number on the tag an individual wears, to suggest as its name."""

    finder: OnnxFile = Field(
        description="ONNX model that finds tags in a picture of an individual, as "
        "a path or an http(s) URL ending in .onnx."
    )
    lines: OnnxFile = Field(
        description="ONNX model that finds the lines of text on a tag, as a path "
        "or an http(s) URL ending in .onnx."
    )
    reader: OnnxFile = Field(
        description="ONNX model that reads a line of text, as a path or an "
        "http(s) URL ending in .onnx."
    )
    digits: PositiveInt = Field(
        default=4,
        description="How many digits the number has; other reads are not suggested.",
    )


class IndividualsConfig(_ConfigModel):
    """Recognise individual animals of tracked classes, shared by every detector."""

    model: OnnxFile = Field(
        description="ONNX embedding model, as a path or an http(s) URL ending in .onnx."
    )
    labels: Annotated[tuple[NonEmptyString, ...], Field(min_length=1)] = Field(
        description="Detection classes whose tracked objects are individuals."
    )
    precision: Annotated[float, Field(gt=0, le=1)] = Field(
        default=0.99,
        description="Share of names that must be right when the installation sets "
        "its naming threshold from its own named sightings.",
    )
    coat: CoatConfig | None = Field(
        default=None,
        description="Also compare coat details; needs pictures of individuals a "
        "few hundred pixels across.",
    )
    tags: TagsConfig | None = Field(
        default=None,
        description="Also read the number on each individual's tag and suggest it "
        "as the name; needs tags some 50 pixels high.",
    )

    @field_validator(
        "labels",
        mode="before",
        json_schema_input_type=NonEmptyString | list[NonEmptyString],
    )
    @classmethod
    def normalize_labels(cls, value: object) -> object:
        return _sequence(value)


class OnnxConfig(_ConfigModel):
    provider: NonEmptyString | None = None
    winml: bool = True
    opset: PositiveInt = 20


class Config(_ConfigModel):
    schema_url: str | None = Field(default=None, alias="$schema")
    detectors: Annotated[tuple[DetectorConfig, ...], Field(min_length=1)]
    onnx: OnnxConfig = Field(default_factory=OnnxConfig)
    health: HealthcheckConfig | None = None
    individuals: IndividualsConfig | None = None

    @model_validator(mode="after")
    def tracked_individuals(self) -> Config:
        if self.individuals is not None and not any(
            detector.yolo is not None and detector.yolo.outlines_tracks
            for detector in self.detectors
        ):
            raise ValueError(
                "Recognising individuals needs a detector with object tracking and a "
                'segmentation model: set "tracking": true and "task": "segment"'
            )
        return self


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
