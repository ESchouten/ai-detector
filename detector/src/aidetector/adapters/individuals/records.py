"""The individuals folder shared with the web application.

```text
individuals/
├── names.json                 written by people: sighting ID -> name
├── groups.json                written by the detector: unnamed look-alikes
└── sightings/<sighting ID>/
    ├── sighting.json          written once by the detector
    ├── crop-1.jpg, ...        the track's best pictures
    └── vectors-<model>.npy    their embeddings, per model file
```
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SightingId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class SightingRecord(BaseModel):
    """One tracked object's best pictures from one event."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    id: SightingId
    # The camera's 12-character ID, as in the logs and archive; never its address.
    camera: str = Field(pattern=r"^[a-f0-9]{12}$")
    label: str
    track: int
    # Source time of the event's best observation, in this computer's local time.
    seen: str
    event_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    crops: int = Field(ge=1)


class NamesFile(BaseModel):
    """The names people gave to sightings; a name is shared by all its sightings."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    names: dict[SightingId, Annotated[str, Field(min_length=1, pattern=r"\S")]] = {}


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
