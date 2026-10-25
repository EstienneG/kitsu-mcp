"""The activity feed, notifications, search and timesheets."""

from pydantic import BaseModel, Field


class ActivityItem(BaseModel):
    """A change on a task from the project's activity feed: a comment, a status change or an upload."""

    date: str | None
    entity: str | None = Field(description="Full entity name, e.g. 'SQ010 / SH020'")
    task_id: str | None
    task_type: str | None
    status: str | None = Field(description="Task status after the change")
    status_changed: bool = Field(description="The change set a new status")
    author: str | None
    comment_id: str | None
    preview_file_id: str | None = Field(None, description="Set when the change uploaded a preview")


class Activity(BaseModel):
    total: int = Field(description="Changes matching the filters in Kitsu (may exceed what is returned)")
    authors: dict[str, int] = Field(description="Changes per person among those returned")
    items: list[ActivityItem]


class Notification(BaseModel):
    date: str | None
    type: str | None = Field(description="comment, mention, assignation, reply, ...")
    read: bool
    project: str | None
    entity: str | None
    task_id: str | None
    task_type: str | None
    status: str | None
    author: str | None
    text: str | None = Field(description="The comment or reply text, when there is one")
    comment_id: str | None


class Notifications(BaseModel):
    total: int = Field(description="Notifications matching the filters")
    unread: int
    notifications: list[Notification]


class SearchHit(BaseModel):
    kind: str = Field(description="asset, shot, sequence, episode, edit, concept or person")
    id: str
    name: str = Field(description="Shots as 'SQ010 / SH010', since shot names repeat across sequences")
    project: str | None = None
    detail: str | None = Field(None, description="Asset type, sequence, or a person's role")


class SearchResults(BaseModel):
    total: int
    hits: list[SearchHit]


class TimesheetDay(BaseModel):
    date: str
    minutes: float


class TimesheetTask(BaseModel):
    task_id: str
    project: str | None
    entity: str | None
    task_type: str | None
    minutes: float


class DayOff(BaseModel):
    start: str | None
    end: str | None
    description: str | None = None


class Timesheet(BaseModel):
    person: str | None
    start: str
    end: str
    total_minutes: float
    by_day: list[TimesheetDay]
    by_task: list[TimesheetTask]
    days_off: list[DayOff] | None = Field(
        default=None, description="Days off overlapping the period; None when Kitsu does not let you see them"
    )
    note: str | None = None
