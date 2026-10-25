"""People, their tasks and their workload."""

from pydantic import BaseModel, Field


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
