from typing import Annotated, Literal

from pydantic import Field

from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import comment, task_detail
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import AssigneeGroup, MyTask, StatusChange, TaskDetail, TaskHistory, TaskList, TaskRow
from kitsu_mcp.production import EntityKind, TaskRecord, day, project_tasks
from kitsu_mcp.validation import Limit, Offset, iso_date, object_id

SortKey = Literal["due_date", "entity", "task_type", "status", "last_comment_date"]


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def get_task(
    task_id: str, include_comments: bool = True, comment_limit: Annotated[int, Field(ge=1, le=200)] = 20
) -> TaskDetail:
    """Get a task with its entity, status, assignees and latest comments (newest first)."""
    task_id = object_id(task_id, "task", "search_tasks")
    client = get_client()
    result = task_detail(client.get(f"data/tasks/{task_id}/full"))
    if include_comments:
        result.comments = [comment(c) for c in client.get(f"data/tasks/{task_id}/comments")[:comment_limit]]
    return result


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def search_tasks(
    project: str,
    task_types: list[str] | None = None,
    statuses: list[str] | None = None,
    assignee: str | None = None,
    unassigned: bool = False,
    entity_kind: EntityKind = "any",
    entity_name_contains: str | None = None,
    group: str | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    overdue: bool = False,
    waiting_feedback: bool = False,
    include_done: bool = True,
    sort_by: SortKey = "due_date",
    group_by: Literal["assignee"] | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> TaskList:
    """Search a project's asset and shot tasks.

    project: name or ID. task_types: names or short names. statuses: status short names.
    assignee: person name, email or ID. group: asset type name or sequence name.
    due_before / due_after: YYYY-MM-DD (inclusive). overdue: due date passed and status not done.
    waiting_feedback: in a status that requests feedback (waiting for review/approval).
    Results are sorted by `sort_by` (missing values last); `total` counts all matches.
    group_by="assignee": instead of task rows, one compact line per task grouped by person (lighter
    for "who owns what"); `total` still counts tasks, `groups` counts people, and limit/offset page
    through the people.
    """
    due_before = iso_date(due_before, "due_before") if due_before else None
    due_after = iso_date(due_after, "due_after") if due_after else None
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    type_ids = {lookups.task_type(t)["id"] for t in task_types or []}
    status_ids = {lookups.task_status(s)["id"] for s in statuses or []}
    person_id = lookups.person(assignee)["id"] if assignee else None
    name_part = (entity_name_contains or "").lower()
    group_part = (group or "").lower()

    def keep(record: TaskRecord) -> bool:
        task = record.raw
        due = day(task.get("due_date"))
        return (
            (not type_ids or task.get("task_type_id") in type_ids)
            and (not status_ids or task.get("task_status_id") in status_ids)
            and (person_id is None or person_id in (task.get("assignees") or []))
            and (not unassigned or not task.get("assignees"))
            and (not name_part or name_part in (record.entity.get("name") or "").lower())
            and (not group_part or group_part in (record.group or "").lower())
            and (not due_before or (due is not None and due <= due_before))
            and (not due_after or (due is not None and due >= due_after))
            and (not overdue or record.is_overdue(lookups))
            and (not waiting_feedback or lookups.status_flag(task.get("task_status_id"), "is_feedback_request"))
            and (include_done or not record.is_done(lookups))
        )

    records = [r for r in project_tasks(get_client(), lookups, project_id, entity_kind) if keep(r)]
    pairs = [(r.row(lookups), r.is_overdue(lookups)) for r in records]
    pairs.sort(key=lambda p: (getattr(p[0], sort_by) is None, getattr(p[0], sort_by) or "", p[0].entity or ""))
    if group_by == "assignee":
        groups = _by_assignee(pairs)
        return TaskList(total=len(pairs), groups=len(groups), by_assignee=groups[offset : offset + limit])
    return TaskList(total=len(pairs), tasks=[row for row, _ in pairs[offset : offset + limit]])


def _by_assignee(pairs: list[tuple[TaskRow, bool]]) -> list[AssigneeGroup]:
    """Group (row, is_overdue) pairs by assignee, busiest first; a task with two assignees counts for both."""
    groups: dict[str, list[tuple[TaskRow, bool]]] = {}
    for row, late in pairs:
        for person in row.assignees or ["(unassigned)"]:
            groups.setdefault(person, []).append((row, late))

    def line(r: TaskRow) -> str:
        details = ", ".join(x for x in (r.status, r.due_date and f"due {r.due_date}") if x)
        return f"{r.entity} / {r.task_type} ({details})"

    return sorted(
        (
            AssigneeGroup(
                assignee=person,
                count=len(items),
                overdue=sum(late for _, late in items),
                tasks=[line(r) for r, _ in items],
            )
            for person, items in groups.items()
        ),
        key=lambda g: (-g.count, g.assignee),
    )


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def task_history(task_id: str) -> TaskHistory:
    """Status changes of a task over time (from its comments), plus time logged vs. estimate."""
    task_id = object_id(task_id, "task", "search_tasks")
    client = get_client()
    task = task_detail(client.get(f"data/tasks/{task_id}/full"))
    comments = [comment(c) for c in reversed(client.get(f"data/tasks/{task_id}/comments"))]
    changes, previous = [], None
    for c in comments:
        if c.status != previous:
            changes.append(
                StatusChange(date=c.date, author=c.author, status=c.status, previous_status=previous, text=c.text)
            )
            previous = c.status
    return TaskHistory(
        id=task.id,
        entity=task.entity,
        task_type=task.task_type,
        current_status=task.status,
        time_logged=task.duration,
        estimation=task.estimation,
        retake_count=task.retake_count,
        changes=changes,
    )


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def my_tasks() -> list[MyTask]:
    """List open tasks assigned to the logged-in user."""
    return [
        MyTask(
            id=t["id"],
            project=t.get("project_name"),
            entity=t.get("entity_name"),
            entity_type=t.get("entity_type_name"),
            task_type=t.get("task_type_name"),
            status=t.get("task_status_short_name"),
            due_date=day(t.get("due_date")),
        )
        for t in get_client().get("data/user/tasks")
    ]
