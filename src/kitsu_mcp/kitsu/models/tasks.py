"""Tasks: as seen from their entity, in detail with comments and history, and as search rows."""

from pydantic import BaseModel, Field

from kitsu_mcp.kitsu.models.review import PreviewFile


class TaskSummary(BaseModel):
    """A task as seen from its entity (asset or shot)."""

    id: str
    task_type: str | None
    status: str | None
    assignees: list[str]
    due_date: str | None = Field(description="YYYY-MM-DD")
    last_comment_date: str | None = None
    last_preview_file_id: str | None = Field(None, description="Latest upload; video tools accept it")


class Reply(BaseModel):
    date: str | None
    author: str | None
    text: str | None


class Comment(BaseModel):
    id: str | None = None
    date: str | None
    author: str | None
    status: str | None
    text: str | None
    preview_ids: list[str] = Field(default_factory=list)
    replies: list[Reply] = Field(default_factory=list)
    acknowledged_by: list[str] = Field(default_factory=list, description="People who acknowledged the comment")


class StatusChange(BaseModel):
    date: str | None
    author: str | None
    status: str | None
    previous_status: str | None
    text: str | None


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
    history: list[StatusChange] | None = Field(
        default=None, description="include_history: status changes, oldest first"
    )
    previews: list[PreviewFile] | None = Field(default=None, description="include_previews: newest revision first")
    url: str | None = Field(None, description="Kitsu web page; open it to watch movies and read comments")


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
