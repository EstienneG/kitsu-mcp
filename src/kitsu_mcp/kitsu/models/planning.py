"""Planning: quotas, the production schedule and the budget."""

from pydantic import BaseModel, Field


class PersonQuota(BaseModel):
    person: str
    total_shots: float = Field(description="Shots counted (fractions in weighted mode)")
    total_frames: float | None = None
    total_seconds: float | None = None
    total_drawings: float | None = None
    shots: dict[str, float] = Field(description="Period -> shots, periods without output left out")
    frames: dict[str, float] | None = None


class Quotas(BaseModel):
    task_type: str
    period: str
    count_mode: str
    since: str | None
    people: list[PersonQuota]


class ScheduleSpan(BaseModel):
    task_type: str
    start: str | None = Field(description="Planned start, YYYY-MM-DD")
    end: str | None = Field(description="Planned end")
    man_days: float | None = None
    open_tasks: int
    first_due: str | None = Field(description="Earliest due date of its tasks")
    last_due: str | None = Field(description="Latest due date of its tasks: after `end` means planned late")
    late: bool = Field(description="Planned end passed with tasks still open")


class Milestone(BaseModel):
    date: str | None
    name: str | None
    task_type: str | None = None


class Schedule(BaseModel):
    project: str
    start: str | None
    end: str | None
    task_types: list[ScheduleSpan]
    late: list[str]
    unscheduled: list[str] = Field(default_factory=list, description="Task types with tasks but no planned dates")
    milestones: list[Milestone]


class BudgetLine(BaseModel):
    person: str | None
    department: str | None
    position: str | None
    seniority: str | None
    start: str | None
    months: int
    daily_rate: float
    cost: float


class Budget(BaseModel):
    project: str
    name: str | None
    revision: int | None
    currency: str | None
    total: float
    by_department: dict[str, float]
    lines: list[BudgetLine]
