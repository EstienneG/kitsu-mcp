"""Raw Zou payloads → output models. Every tool formats through here."""

from kitsu_mcp.lookups import Lookups
from kitsu_mcp.models import Comment, TaskDetail, TaskSummary


def task_summary(task: dict, lookups: Lookups) -> TaskSummary:
    return TaskSummary(
        id=task["id"],
        task_type=lookups.name("task_types", task.get("task_type_id")),
        status=lookups.name("task_statuses", task.get("task_status_id"), "short_name"),
        assignees=[lookups.person_name(a) or a for a in task.get("assignees") or []],
        due_date=task.get("due_date"),
    )


def comment(raw: dict) -> Comment:
    person = raw.get("person") or {}
    author = person.get("full_name") or " ".join(p for p in (person.get("first_name"), person.get("last_name")) if p)
    return Comment(
        date=raw.get("created_at"),
        author=author or None,
        status=(raw.get("task_status") or {}).get("short_name"),
        text=raw.get("text"),
        preview_ids=[p["id"] for p in raw.get("previews") or [] if isinstance(p, dict) and "id" in p],
    )


def task_detail(task: dict) -> TaskDetail:
    """Format a `data/tasks/<id>/full` payload."""
    return TaskDetail(
        id=task["id"],
        project=(task.get("project") or {}).get("name"),
        entity=(task.get("entity") or {}).get("name"),
        entity_type=(task.get("entity_type") or {}).get("name"),
        task_type=(task.get("task_type") or {}).get("name"),
        status=(task.get("task_status") or {}).get("short_name"),
        assignees=[p.get("full_name") or p["id"] for p in task.get("persons") or []],
        due_date=task.get("due_date"),
        start_date=task.get("start_date"),
        estimation=task.get("estimation"),
        duration=task.get("duration"),
        retake_count=task.get("retake_count"),
    )
