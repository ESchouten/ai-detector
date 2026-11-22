"""The individuals folder shared with the web application.

```text
individuals/
├── names.json                 written by people: sighting ID -> name, and which were a Yes
├── groups.json                written by the detector: unnamed look-alikes
└── sightings/<sighting ID>/
    ├── sighting.json          written once by the detector
    ├── crop-1.jpg, ...        the track's best pictures, whole
    ├── vectors-<model>.npy    their embeddings, per model file
    ├── later-<model>.npy      embeddings of the track's later pictures
    ├── coat-<models>.json     coat details shared with named pictures
    └── tag.json, tag-*.jpg    what the tags on the track's pictures showed
```
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SightingId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class SightingRecord(BaseModel):
    """One tracked object's best pictures, saved once it has been seen a while."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    id: SightingId
    # The camera's 12-character ID, as in the logs and archive; never its address.
    camera: str = Field(pattern=r"^[a-f0-9]{12}$")
    label: str
    track: int
    # Source time the track was first seen, in this computer's local time.
    seen: str
    # The event that saved it; tracks seen before their event are saved without.
    event_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    crops: int = Field(ge=1)
    # Each picture's outline as [x, y] points in its pixels, empty without a
    # segmentation model; the model sees the pictures grey outside them.
    outlines: list[list[tuple[int, int]]] = []


class CoatRecord(BaseModel):
    """The coat details a named sighting shares with other sightings' pictures."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    # Per other sighting, the count for each of its pictures compared, by place.
    shared: dict[SightingId, dict[int, int]]


class TagCrop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # What the tag's number line read as, and how sure the reader was.
    read: str
    confidence: float


class TagRecord(BaseModel):
    """What the tags on a track's pictures showed, replaced as more are seen."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    # The number the reader was sure of on more than one tag picture, for a
    # person to confirm: read from tag-read.jpg, which is the part `box` (x1,
    # y1, x2, y2) of tag-picture.jpg.
    number: str | None = None
    box: tuple[int, int, int, int] | None = None
    # tag-1.jpg and onwards: the tallest tags seen, to train a reader with.
    crops: list[TagCrop] = []


class NamesFile(BaseModel):
    """The names people gave to sightings; a name is shared by all its sightings."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    names: dict[SightingId, Annotated[str, Field(min_length=1, pattern=r"\S")]] = {}
    # Sightings named by answering Yes to the detector's own guess.
    confirmed: list[SightingId] = []


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float


class SightingGroup(BaseModel):
    """Unnamed sightings that look alike, and the named individuals they resemble."""

    model_config = ConfigDict(extra="forbid")

    sightings: list[SightingId] = Field(min_length=1)
    suggestions: list[Suggestion]


class GroupsFile(BaseModel):
    """The latest unnamed sightings in look-alike groups, largest first.

    Rewritten after new sightings; a sighting named since may still be listed.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    # The model file whose embeddings were grouped.
    model: str
    groups: list[SightingGroup]
