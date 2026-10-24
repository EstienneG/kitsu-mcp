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
