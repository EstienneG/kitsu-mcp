"""What the write tools return: results, playlist changes and dry-run plans."""

from typing import Any

from pydantic import BaseModel, Field

from kitsu_mcp.kitsu.models.review import PlaylistDetail
from kitsu_mcp.kitsu.models.tasks import TaskDetail


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


class PlannedRequest(BaseModel):
    method: str = Field(description="POST or PUT")
    path: str = Field(description="Zou API route")
    payload: dict[str, Any]


class DryRunResult(BaseModel):
    """What a write tool would do (dry_run=True). Nothing was sent to Kitsu."""

    dry_run: bool = True
    ok: bool = Field(description="False when a check failed: the real call would be refused")
    verdict: str = Field(description='"would_succeed" or "would_fail"')
    would: str = Field(description="The action, in one line")
    reason: str | None = Field(None, description="Why it would fail")
    requests: list[PlannedRequest] = Field(
        default_factory=list, description="Exactly what the real call sends, in order"
    )
    before: dict[str, Any] = Field(default_factory=dict, description="Current values of the fields that change")
    after: dict[str, Any] = Field(default_factory=dict, description="Their values after the write")
    warnings: list[str] = Field(default_factory=list, description="Allowed, but worth showing the user")
