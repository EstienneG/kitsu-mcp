"""Tool output models. They define the output schemas the MCP clients see."""

from typing import Any

from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    full_name: str | None
    email: str | None
    role: str | None


class Project(BaseModel):
    id: str
    name: str
    production_type: str | None
    status: str | None = None


class TaskType(BaseModel):
    id: str
    name: str
    short_name: str | None
    for_entity: str | None


class TaskStatus(BaseModel):
    id: str
    name: str
    short_name: str
    is_done: bool | None = None
    is_wip: bool | None = None
    is_retake: bool | None = None
    is_feedback_request: bool | None = None


class Named(BaseModel):
    id: str
    name: str


class TaskSummary(BaseModel):
    """A task as seen from its entity (asset or shot)."""

    id: str
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None


class Comment(BaseModel):
    date: str | None
    author: str | None
    status: str | None
    text: str | None
    preview_ids: list[str] = Field(default_factory=list)


class TaskDetail(BaseModel):
    id: str
    project: str | None
    entity: str | None
    entity_type: str | None
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None
    start_date: str | None = None
    estimation: float | None = Field(None, description="Minutes")
    duration: float | None = Field(None, description="Minutes logged")
    retake_count: int | None = None
    comments: list[Comment] | None = None


class TaskRow(BaseModel):
    """A task with its entity context, as returned by searches."""

    id: str
    entity_id: str
    entity: str | None
    entity_kind: str = Field(description="asset or shot")
    group: str | None = Field(description="Asset type, or episode/sequence for shots")
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None
    estimation: float | None = Field(None, description="Minutes")
    duration: float | None = Field(None, description="Minutes logged")
    retake_count: int | None = None
    last_comment_date: str | None = None


class TaskList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    tasks: list[TaskRow]


class StatusChange(BaseModel):
    date: str | None
    author: str | None
    status: str | None
    previous_status: str | None
    text: str | None


class TaskHistory(BaseModel):
    id: str
    entity: str | None
    task_type: str | None
    current_status: str | None
    time_logged: float | None = Field(description="Minutes")
    estimation: float | None = Field(description="Minutes")
    retake_count: int | None
    changes: list[StatusChange] = Field(description="Status changes, oldest first")


class MyTask(BaseModel):
    id: str
    project: str | None
    entity: str | None
    entity_type: str | None
    task_type: str | None
    status: str | None
    due_date: str | None


class AssetSummary(BaseModel):
    id: str
    name: str
    type: str | None
    tasks: list[TaskSummary]


class AssetList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    assets: list[AssetSummary]


class AssetDetail(BaseModel):
    id: str
    name: str
    type: str | None
    description: str | None
    project_id: str | None
    data: dict[str, Any] | None
    tasks: list[TaskSummary]


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
    tasks: list[TaskSummary]


class ShotList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    shots: list[ShotSummary]


class ShotDetail(ShotSummary):
    project_id: str | None
    description: str | None
    fps: str | None
    data: dict[str, Any] | None


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


class Person(BaseModel):
    id: str
    full_name: str | None
    email: str | None
    role: str | None
    position: str | None = None
    departments: list[str] = Field(default_factory=list)


class PersonTask(BaseModel):
    id: str
    project: str | None
    entity: str | None
    entity_type: str | None
    sequence: str | None
    task_type: str | None
    status: str | None
    due_date: str | None
    estimation: float | None = Field(None, description="Minutes")
    duration: float | None = Field(None, description="Minutes logged")
    last_comment_date: str | None = None


class Workload(BaseModel):
    person: str
    open_tasks: int
    overdue: int
    waiting_feedback: int = Field(description="Tasks in a feedback-request status (e.g. waiting for approval)")
    retakes: int
    estimation: float = Field(description="Minutes estimated over open tasks")
    logged: float = Field(description="Minutes logged over open tasks")
    next_due: str | None


class StatusCount(BaseModel):
    status: str
    count: int


class TaskTypeProgress(BaseModel):
    task_type: str
    total: int
    done: int
    done_ratio: float
    statuses: list[StatusCount]


class ProjectOverview(BaseModel):
    project: str
    production_type: str | None
    start_date: str | None
    end_date: str | None
    fps: str | None
    resolution: str | None
    assets: int
    shots: int
    tasks: int
    done_ratio: float
    overdue: int
    waiting_feedback: int
    retakes: int
    unassigned_open: int
    estimation: float = Field(description="Minutes estimated over all tasks")
    logged: float = Field(description="Minutes logged over all tasks")
    by_task_type: list[TaskTypeProgress]


class PreviewFile(BaseModel):
    id: str
    revision: int | None
    extension: str | None
    is_movie: bool | None
    original_name: str | None
    status: str | None
    validation_status: str | None
    width: int | None
    height: int | None
    created_at: str | None


class SavedPreview(BaseModel):
    kind: str
    id: str
    name: str
    path: str


class FailedPreview(BaseModel):
    name: str
    error: str


class DownloadResult(BaseModel):
    saved: list[SavedPreview]
    skipped: int = Field(description="Entities without a preview, canceled, or already downloaded")
    failed: list[FailedPreview]


class Playlist(BaseModel):
    id: str
    name: str
    for_entity: str | None
    for_client: bool | None
    task_type: str | None
    updated_at: str | None


class PlaylistItem(BaseModel):
    entity_id: str
    entity: str | None
    preview_file_id: str | None


class PlaylistDetail(Playlist):
    items: list[PlaylistItem]


class WriteResult(BaseModel):
    ok: bool
    message: str
    task: TaskDetail | None = None
