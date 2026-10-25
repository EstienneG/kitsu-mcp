"""Assets, sequences, shots, casting and custom fields."""

from typing import Any

from pydantic import BaseModel, Field

from kitsu_mcp.kitsu.models.tasks import TaskSummary


class AssetSummary(BaseModel):
    id: str
    name: str
    type: str | None
    tasks: list[TaskSummary] | None = None
    statuses: dict[str, str | None] | None = Field(default=None, description='detail="compact": task type -> status')
    custom_fields: dict[str, Any] | None = Field(default=None, description='detail="full": by display name')


class AssetList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    assets: list[AssetSummary]


class AssetDetail(BaseModel):
    id: str
    name: str
    type: str | None
    description: str | None
    project_id: str | None
    custom_fields: dict[str, Any] | None = Field(
        default_factory=dict, description="Custom field values by display name (list_custom_fields); unset = null"
    )
    extra_data: dict[str, Any] = Field(
        default_factory=dict, description="Other non-empty values Kitsu keeps in the entity's data (handles, ...)"
    )
    tasks: list[TaskSummary]
    url: str | None = Field(None, description="Kitsu web page; open it to watch movies and read comments")


class Sequence(BaseModel):
    id: str
    name: str
    episode: str | None = None
    description: str | None = None


class ShotSummary(BaseModel):
    id: str
    name: str
    sequence: str | None
    episode: str | None
    frame_in: int | None
    frame_out: int | None
    nb_frames: int | None
    tasks: list[TaskSummary] | None = None
    statuses: dict[str, str | None] | None = Field(default=None, description='detail="compact": task type -> status')
    custom_fields: dict[str, Any] | None = Field(default=None, description='detail="full": by display name')


class ShotList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    shots: list[ShotSummary]


class ShotDetail(ShotSummary):
    project_id: str | None
    description: str | None
    fps: float | None
    custom_fields: dict[str, Any] | None = Field(
        default_factory=dict, description="Custom field values by display name (list_custom_fields); unset = null"
    )
    extra_data: dict[str, Any] = Field(
        default_factory=dict, description="Other non-empty values Kitsu keeps in the entity's data (handles, ...)"
    )
    url: str | None = Field(None, description="Kitsu web page; open it to watch movies and read comments")


class EntitySummary(BaseModel):
    """A concept, edit, scene, sequence or episode in a list (list_entities)."""

    id: str
    name: str
    kind: str
    description: str | None = None
    statuses: dict[str, str | None] = Field(default_factory=dict, description="task type -> status")


class EntityDetail(BaseModel):
    """A concept, edit, scene, sequence or episode (get_entity)."""

    id: str
    name: str
    kind: str
    project_id: str | None
    description: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict, description="Values Kitsu keeps in the entity's data")
    tasks: list[TaskSummary] = Field(default_factory=list)


class CastAsset(BaseModel):
    asset_id: str
    name: str | None
    asset_type: str | None
    occurrences: int | None
    label: str | None = None


class CastIn(BaseModel):
    shot_id: str
    shot: str | None
    sequence: str | None
    episode: str | None
    occurrences: int | None


class ShotCasting(BaseModel):
    """One shot of a sequence and the assets cast in it (get_casting with sequence_id)."""

    shot_id: str
    shot: str | None
    assets: list[CastAsset]


class CustomField(BaseModel):
    """A project's custom field (Kitsu "metadata descriptor")."""

    name: str = Field(description="Display name; custom_fields and custom_field_filters use it")
    field_name: str = Field(description="Key in the entity's data")
    entity_type: str = Field(description="Asset, Shot, Sequence, Episode or Edit")
    data_type: str = Field(description="string, number, boolean, date, list, taglist, checklist, ...")
    choices: list[str] = Field(default_factory=list, description='The allowed values of a "list" field')
    departments: list[str] = Field(default_factory=list, description="Departments it is shown to (empty: everyone)")
    for_client: bool = False
