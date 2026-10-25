"""The server, the signed-in user, projects and their reference data (task types, statuses, overview)."""

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
    done_improvable: int = Field(
        0, description="Done by role but not flagged done in Kitsu (e.g. a 'could be better' status)"
    )
    done_improvable_statuses: list[str] = Field(default_factory=list)
    overdue: int = Field(description="Open tasks past their due date, not on hold")
    waiting_feedback: int = Field(description="Open tasks waiting for review/approval")
    retakes: int
    on_hold: int = Field(0, description="Open tasks paused (STAND BY, PAUSE, BLOCKED, ...)")
    unassigned_open: int
    estimation: float = Field(description="Minutes estimated over all tasks")
    logged: float = Field(description="Minutes logged over all tasks")
    by_task_type: list[TaskTypeProgress] = Field(description="Progress per group (see grouped_by)")
    grouped_by: str = Field(default="task_type", description="task_type, sequence, episode or asset_type")
