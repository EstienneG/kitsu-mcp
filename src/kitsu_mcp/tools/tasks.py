from typing import Literal

from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import comment, task_detail
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import MyTask, StatusChange, TaskDetail, TaskHistory, TaskList
from kitsu_mcp.production import EntityKind, TaskRecord, day, project_tasks
from kitsu_mcp.validation import iso_date

SortKey = Literal["due_date", "entity", "task_type", "status", "last_comment_date"]


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def get_task(task_id: str, include_comments: bool = True, comment_limit: int = 20) -> TaskDetail:
    """Get a task with its entity, status, assignees and latest comments (newest first)."""
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
    include_done: bool = True,
    sort_by: SortKey = "due_date",
    limit: int = 100,
    offset: int = 0,
) -> TaskList:
    """Search a project's asset and shot tasks.

    project: name or ID. task_types: names or short names. statuses: status short names.
    assignee: person name, email or ID. group: asset type name or sequence name.
    due_before / due_after: YYYY-MM-DD (inclusive). overdue: due date passed and status not done.
    Results are sorted by `sort_by` (missing values last); `total` counts all matches.
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
            and (include_done or not record.is_done(lookups))
        )

    rows = [r.row(lookups) for r in project_tasks(get_client(), lookups, project_id, entity_kind) if keep(r)]
    rows.sort(key=lambda r: (getattr(r, sort_by) is None, getattr(r, sort_by) or "", r.entity or ""))
    return TaskList(total=len(rows), tasks=rows[offset : offset + limit])


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def task_history(task_id: str) -> TaskHistory:
    """Status changes of a task over time (from its comments), plus time logged vs. estimate."""
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
            due_date=t.get("due_date"),
        )
        for t in get_client().get("data/user/tasks")
    ]
