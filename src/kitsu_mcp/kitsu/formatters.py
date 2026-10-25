"""Raw Zou payloads → output models. Every tool formats through here."""

from kitsu_mcp.kitsu import links
from kitsu_mcp.kitsu.lookups import Lookups
from kitsu_mcp.kitsu.models import Comment, Reply, TaskDetail, TaskSummary


def day(value: str | None) -> str | None:
    """Zou dates come as `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`; tools report the day."""
    return value[:10] if value else None


def task_summary(task: dict, lookups: Lookups) -> TaskSummary:
    return TaskSummary(
        id=task["id"],
        task_type=lookups.name("task_types", task.get("task_type_id")),
        status=lookups.name("task_statuses", task.get("task_status_id"), "short_name"),
        assignees=[lookups.person_name(a) or a for a in task.get("assignees") or []],
        due_date=day(task.get("due_date")),
        last_comment_date=task.get("last_comment_date"),
        last_preview_file_id=task.get("last_preview_file_id"),
    )


def _author(raw: dict) -> str | None:
    person = raw.get("person") or {}
    author = person.get("full_name") or " ".join(p for p in (person.get("first_name"), person.get("last_name")) if p)
    return author or None


def comment(raw: dict, lookups: Lookups | None = None) -> Comment:
    """`lookups` names the people who acknowledged the comment (Zou only gives their IDs)."""
    acknowledged = raw.get("acknowledgements") or []
    return Comment(
        id=raw.get("id"),
        date=raw.get("created_at"),
        author=_author(raw),
        status=(raw.get("task_status") or {}).get("short_name"),
        text=raw.get("text"),
        preview_ids=[p["id"] for p in raw.get("previews") or [] if isinstance(p, dict) and "id" in p],
        replies=[
            Reply(date=r.get("created_at") or r.get("date"), author=_author(r), text=r.get("text"))
            for r in raw.get("replies") or []
            if isinstance(r, dict)
        ],
        acknowledged_by=[(lookups.person_name(a) if lookups else None) or a for a in acknowledged],
    )


def task_detail(task: dict) -> TaskDetail:
    """Format a `data/tasks/<id>/full` payload."""
    return TaskDetail(
        id=task["id"],
        project=(task.get("project") or {}).get("name"),
        entity=(task.get("entity") or {}).get("name"),
        entity_id=task.get("entity_id") or (task.get("entity") or {}).get("id"),
        entity_type=(task.get("entity_type") or {}).get("name"),
        task_type=(task.get("task_type") or {}).get("name"),
        status=(task.get("task_status") or {}).get("short_name"),
        assignees=[p.get("full_name") or p["id"] for p in task.get("persons") or []],
        due_date=day(task.get("due_date")),
        start_date=day(task.get("start_date")),
        estimation=task.get("estimation"),
        duration=task.get("duration"),
        retake_count=task.get("retake_count"),
        last_comment_date=task.get("last_comment_date"),
        last_preview_file_id=task.get("last_preview_file_id"),
        url=task_link(task),
    )


def task_link(task: dict, preview_file_id: str | None = None) -> str | None:
    """Kitsu page of a `data/tasks/<id>/full` task. Zou leaves `episode` unset when the task's entity is
    itself an Episode, so Kitsu's getTaskPath uses the entity ID there; so do we."""
    for_entity = (task.get("task_type") or {}).get("for_entity")
    if (for_entity or "").lower() == "episode":
        episode_id = task.get("entity_id") or (task.get("entity") or {}).get("id")
    else:
        episode_id = (task.get("episode") or {}).get("id")
    return links.task_url(task.get("project_id"), task["id"], for_entity, episode_id, preview_file_id)
