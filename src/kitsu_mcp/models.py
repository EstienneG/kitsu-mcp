"""Tool output models. They define the output schemas the MCP clients see."""

from typing import Any

from pydantic import BaseModel, Field


class ServerInfo(BaseModel):
    """How this server is set up: what an agent can and cannot do here."""

    version: str
    kitsu_host: str
    write_tools: bool = Field(description="add_comment, set_task_status, ... available (KITSU_ALLOW_WRITE)")
    video_tools: bool = Field(description="The video extra (PyAV, Pillow) is installed")
    max_page_size: int
    status_role_settings: dict[str, list[str]] = Field(
        description="KITSU_*_STATUSES: status names given each role; list_task_statuses shows the result"
    )
    unmatched_status_settings: dict[str, list[str]] = Field(description="Configured names that match no status")
    cache_ttl_seconds: float
    video_max_mb: int


class User(BaseModel):
    id: str
    full_name: str | None
    email: str | None
    role: str | None
    server: ServerInfo | None = None


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
    role: str = Field(description="What it means here: omitted, done, on_hold, retake, waiting_review, wip or todo")
    role_source: str = Field(description='"kitsu flags", or the KITSU_*_STATUSES setting that set the role')
    is_done: bool | None = None
    is_wip: bool | None = None
    is_retake: bool | None = None
    is_feedback_request: bool | None = None


class TaskStatuses(BaseModel):
    statuses: list[TaskStatus]
    unmatched_settings: dict[str, list[str]] = Field(
        default_factory=dict, description="Names in KITSU_*_STATUSES settings that match no status (typos?)"
    )


class Named(BaseModel):
    id: str
    name: str


class TaskSummary(BaseModel):
    """A task as seen from its entity (asset or shot)."""

    id: str
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None = Field(description="YYYY-MM-DD")
    last_comment_date: str | None = None
    last_preview_file_id: str | None = Field(None, description="Latest upload; video tools accept it")


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
    entity_id: str | None = None
    entity_type: str | None
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None = Field(description="YYYY-MM-DD")
    start_date: str | None = None
    estimation: float | None = Field(None, description="Minutes")
    duration: float | None = Field(None, description="Minutes logged")
    retake_count: int | None = None
    last_comment_date: str | None = None
    last_preview_file_id: str | None = Field(None, description="Latest upload; video tools accept it")
    comments: list[Comment] | None = None


class TaskBrief(BaseModel):
    """A task row with only what is needed to scan a list (detail="compact")."""

    id: str
    entity: str | None
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None


class TaskRow(TaskBrief):
    """A task with its entity context, as returned by searches (detail="full")."""

    entity_id: str
    entity_kind: str = Field(description="asset or shot")
    group: str | None = Field(description="Asset type, or episode/sequence for shots")
    estimation: float | None = Field(None, description="Minutes")
    duration: float | None = Field(None, description="Minutes logged")
    retake_count: int | None = None
    last_comment_date: str | None = None
    last_preview_file_id: str | None = None


class AssigneeGroup(BaseModel):
    assignee: str
    count: int = Field(description="All of this person's matching tasks")
    overdue: int
    tasks: list[str] = Field(description="'entity / task type (status, due date)', at most tasks_per_group")
    more: int = Field(0, description="Tasks not listed in `tasks` (raise tasks_per_group to see them)")


class TaskList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    tasks: list[TaskRow | TaskBrief] = Field(default_factory=list)
    groups: int | None = Field(default=None, description="With group_by: number of groups before limit/offset")
    by_assignee: list[AssigneeGroup] | None = Field(
        default=None, description="Set with group_by='assignee', instead of tasks"
    )


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
    tasks: list[TaskSummary] | None = None
    statuses: dict[str, str | None] | None = Field(default=None, description='detail="compact": task type -> status')


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
    tasks: list[TaskSummary] | None = None
    statuses: dict[str, str | None] | None = Field(default=None, description='detail="compact": task type -> status')


class ShotList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    shots: list[ShotSummary]


class ShotDetail(ShotSummary):
    project_id: str | None
    description: str | None
    fps: float | None
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
    email: str | None = None
    role: str | None
    position: str | None = None
    departments: list[str] = Field(default_factory=list)


class PeopleList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    people: list[Person]


class PersonTaskBrief(BaseModel):
    """A person's task with only what is needed to scan a list (detail="compact")."""

    id: str
    project: str | None
    entity: str | None
    entity_type: str | None
    task_type: str | None
    status: str | None
    due_date: str | None


class PersonTask(PersonTaskBrief):
    """detail="full"."""

    sequence: str | None
    estimation: float | None = Field(None, description="Minutes")
    duration: float | None = Field(None, description="Minutes logged")
    last_comment_date: str | None = None


class PersonTaskList(BaseModel):
    total: int = Field(description="Matches before limit/offset")
    tasks: list[PersonTask | PersonTaskBrief]


class Workload(BaseModel):
    person: str
    open_tasks: int
    overdue: int
    waiting_feedback: int = Field(description="Open tasks waiting for review/approval")
    retakes: int
    on_hold: int = Field(0, description="Open tasks paused (STAND BY, PAUSE, BLOCKED, ...)")
    estimation: float = Field(description="Minutes estimated over open tasks")
    logged: float = Field(description="Minutes logged over open tasks")
    next_due: str | None


class StatusCount(BaseModel):
    status: str
    count: int


class TaskTypeProgress(BaseModel):
    task_type: str
    total: int
    done: int = Field(description="Finished tasks (status role done), not counting omitted ones")
    omitted: int = Field(0, description="Dropped tasks (OMIT, N/A, ...), left out of done_ratio")
    done_ratio: float = Field(description="done / (total - omitted)")
    statuses: list[StatusCount]


class ProjectOverview(BaseModel):
    project: str
    production_type: str | None
    start_date: str | None
    end_date: str | None
    fps: float | None
    resolution: str | None
    assets: int
    shots: int
    tasks: int
    omitted: int = Field(0, description="Dropped tasks (OMIT, N/A, ...), left out of done_ratio")
    omitted_statuses: list[str] = Field(default_factory=list, description="Statuses counted as omitted")
    done_ratio: float = Field(description="Finished tasks / (tasks - omitted)")
    done_improvable: int = Field(0, description="Done tasks that could still be improved (e.g. CBB)")
    done_improvable_statuses: list[str] = Field(default_factory=list)
    overdue: int = Field(description="Open tasks past their due date, not on hold")
    waiting_feedback: int = Field(description="Open tasks waiting for review/approval")
    retakes: int
    on_hold: int = Field(0, description="Open tasks paused (STAND BY, PAUSE, BLOCKED, ...)")
    unassigned_open: int
    estimation: float = Field(description="Minutes estimated over all tasks")
    logged: float = Field(description="Minutes logged over all tasks")
    by_task_type: list[TaskTypeProgress]


class PreviewFile(BaseModel):
    id: str
    revision: int | None
    position: int | None = Field(None, description="Order within the revision; 1 is the main file")
    extension: str | None
    is_movie: bool | None
    original_name: str | None
    status: str | None
    validation_status: str | None
    width: int | None
    height: int | None
    created_at: str | None
    is_video: bool = Field(
        default=False, description="A movie, detected from the extension (is_movie is unreliable); see the video tools"
    )
    duration: float | None = Field(default=None, description="Seconds, for movies")
    note: str | None = None


class RecentPreview(BaseModel):
    """An upload from the project's activity feed."""

    date: str | None
    entity: str | None = Field(description="Full entity name, e.g. 'SQ010 / SH020'")
    entity_id: str | None
    task_id: str | None
    task_type: str | None
    status: str | None = Field(description="Task status set with the upload")
    author: str | None
    preview_file_id: str
    revision: int | None
    extension: str | None
    is_video: bool


class RecentPreviews(BaseModel):
    total: int = Field(description="Uploads matching the filters in Kitsu (may exceed what is returned)")
    previews: list[RecentPreview]


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
    skipped: int = Field(description="All entities not downloaded: the sum of the next three counts")
    no_preview: int = 0
    canceled: int = 0
    already_downloaded: int = Field(0, description="File already in dest_dir (pass overwrite=True to replace)")
    failed: list[FailedPreview]


class Playlist(BaseModel):
    id: str
    name: str
    for_entity: str | None
    for_client: bool | None
    task_type: str | None
    updated_at: str | None


class PlaylistList(BaseModel):
    total: int = Field(description="Playlists before limit/offset")
    playlists: list[Playlist]


class PlaylistItem(BaseModel):
    entity_id: str
    entity: str | None
    preview_file_id: str | None


class PlaylistDetail(Playlist):
    items: list[PlaylistItem]


class VideoInfo(BaseModel):
    preview_file_id: str
    task_id: str | None
    revision: int | None
    original_name: str | None
    extension: str | None
    quality: str = Field(description="Which file was probed: low (Kitsu's web-playback encode) or original")
    file_bytes: int
    codec: str | None
    width: int
    height: int
    fps: float
    duration: float = Field(description="Seconds")
    frame_count: int = Field(description="Frames are numbered 1..frame_count, like Kitsu's player")
    kitsu_width: int | None = None
    kitsu_height: int | None = None
    kitsu_duration: float | None = None
    original_file_size: int | None = Field(None, description="Bytes of the uploaded file")
    annotated_frames: list[int] = Field(default_factory=list, description="Frames with drawings in Kitsu")


class SavedVideo(BaseModel):
    preview_file_id: str
    path: str
    quality: str
    bytes: int
    skipped: bool = Field(default=False, description="The file already existed and overwrite was False")


class WriteResult(BaseModel):
    ok: bool
    message: str
    task: TaskDetail | None = None


class PlaylistEntry(BaseModel):
    entity_id: str
    entity: str | None
    task_type: str | None = Field(None, description="Task the preview comes from")
    revision: int | None = None
    preview_file_id: str | None


class SkippedEntry(BaseModel):
    ref: str = Field(description="The task or entity ID as passed")
    entity: str | None
    reason: str


class PlaylistWriteResult(BaseModel):
    ok: bool
    message: str
    added: list[PlaylistEntry] = Field(default_factory=list)
    skipped: list[SkippedEntry] = Field(default_factory=list)
    playlist: PlaylistDetail | None = Field(None, description="The playlist after the change")
