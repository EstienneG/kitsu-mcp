"""Tools that modify Kitsu. Registered disabled; `main()` enables them when KITSU_ALLOW_WRITE=true."""

from datetime import date

from fastmcp.exceptions import ToolError

from kitsu_mcp.app import mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import task_detail
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import WriteResult
from kitsu_mcp.validation import iso_date

WRITE = {"write"}
# Each call adds something (a comment, logged time): repeating it duplicates the effect.
ADDITIVE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
# Adds an assignee; repeating it is harmless.
ADDITIVE_IDEMPOTENT = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
# Replaces existing values.
OVERWRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}


def _task(task_id: str) -> dict:
    return get_client().get(f"data/tasks/{task_id}/full")


def _result(message: str, task_id: str) -> WriteResult:
    """The write already succeeded: a failing re-read must not make it look failed (and invite a retry)."""
    try:
        task = task_detail(_task(task_id))
    except Exception as error:  # noqa: BLE001 - any failure here happens after a successful write
        return WriteResult(ok=True, message=f"{message} (Could not reload the task: {error})", task=None)
    return WriteResult(ok=True, message=message, task=task)


def _comment(task_id: str, text: str, status: str | None) -> tuple[dict, str]:
    """Post a comment; Kitsu requires a status on every comment, so default to the current one."""
    task = _task(task_id)
    status_id = get_lookups().task_status(status)["id"] if status else task["task_status_id"]
    get_client().post(f"actions/tasks/{task_id}/comment", {"task_status_id": status_id, "comment": text})
    return task, get_lookups().name("task_statuses", status_id, "short_name") or status_id


@mcp.tool(annotations=ADDITIVE, tags=WRITE)
def add_comment(task_id: str, text: str, status: str | None = None) -> WriteResult:
    """Post a comment on a task as the logged-in user, optionally changing its status (short name)."""
    if not text.strip():
        raise ToolError("Comment text is empty; use set_task_status to change the status without a comment")
    task, status_name = _comment(task_id, text, status)
    changed = status_name != task["task_status"]["short_name"]
    return _result(f"Comment posted{f'; status set to {status_name}' if changed else ''}.", task_id)


@mcp.tool(annotations={**ADDITIVE, "destructiveHint": True}, tags=WRITE)
def set_task_status(task_id: str, status: str, comment: str = "") -> WriteResult:
    """Change a task's status (short name, e.g. wip, wfa, done), with an optional comment.

    Kitsu records every status change as a comment, so each call adds one to the task.
    """
    task, status_name = _comment(task_id, comment, status)
    previous = task["task_status"]["short_name"]
    if previous == status_name:
        return _result(f"Status was already {status_name}; comment posted.", task_id)
    return _result(f"Status changed from {previous} to {status_name}.", task_id)


@mcp.tool(annotations=ADDITIVE_IDEMPOTENT, tags=WRITE)
def assign_task(task_id: str, person: str) -> WriteResult:
    """Add a person (name, email or ID) to a task's assignees."""
    record = get_lookups().person(person)
    get_client().put(f"actions/persons/{record['id']}/assign", {"task_ids": [task_id]})
    return _result(f"Assigned {record.get('full_name')}.", task_id)


@mcp.tool(annotations=OVERWRITE, tags=WRITE)
def update_task_schedule(
    task_id: str,
    start_date: str | None = None,
    due_date: str | None = None,
    estimation_minutes: float | None = None,
) -> WriteResult:
    """Set a task's start date, due date (YYYY-MM-DD) and/or estimate (minutes). Omitted fields are unchanged."""
    changes: dict = {}
    if start_date is not None:
        changes["start_date"] = iso_date(start_date, "start_date")
    if due_date is not None:
        changes["due_date"] = iso_date(due_date, "due_date")
    if estimation_minutes is not None:
        if estimation_minutes < 0:
            raise ToolError("estimation_minutes must be >= 0")
        changes["estimation"] = estimation_minutes
    if not changes:
        raise ToolError("Nothing to update: pass start_date, due_date or estimation_minutes")
    get_client().put(f"data/tasks/{task_id}", changes)
    return _result(f"Updated {', '.join(changes)}.", task_id)


@mcp.tool(annotations=ADDITIVE, tags=WRITE)
def log_time(task_id: str, minutes: int, day: str | None = None, person: str | None = None) -> WriteResult:
    """Add time spent on a task (minutes) for a day (YYYY-MM-DD, default today), as the logged-in user by default."""
    if not 0 < minutes <= 24 * 60:
        raise ToolError("minutes must be between 1 and 1440")
    when = iso_date(day, "day") if day else date.today().isoformat()
    person_id = get_lookups().person(person)["id"] if person else get_client().user_id()
    get_client().post(f"actions/tasks/{task_id}/time-spents/{when}/persons/{person_id}/add", {"duration": minutes})
    return _result(f"Logged {minutes} min on {when}.", task_id)
