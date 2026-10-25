"""Time logged on tasks."""

from datetime import date

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.formatters import day
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, WriteResult
from kitsu_mcp.kitsu.plans import Plan, current_user
from kitsu_mcp.kitsu.validation import iso_date, object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import (
    ADDITIVE,
    WRITE,
    fetch_task_full,
    send_or_preview,
    task_label,
    warn_unless_lead,
)


def _logged(task_id: str, person_id: str, when: str) -> float:
    """Minutes `person_id` already logged on the task that day (from Zou's `{person_id: [entries]}` answer)."""
    entries = get_client().get(f"actions/tasks/{task_id}/time-spents").get(person_id) or []
    return sum(e.get("duration") or 0 for e in entries if isinstance(e, dict) and day(e.get("date")) == when)


@tool(annotations=ADDITIVE, tags=WRITE)
def log_time(
    task_id: str, minutes: int, day: str | None = None, person: str | None = None, dry_run: bool = False
) -> WriteResult | DryRunResult:
    """Add time spent on a task (minutes) for a day (YYYY-MM-DD, default today), as the logged-in user by default.

    dry_run=True: check everything with reads only and return the plan instead of writing: `would`, the
    exact `requests`, the time logged `before`/`after` (task total and that person's day) and `warnings`;
    verdict "would_fail" gives the `reason` the real call would be refused (over 24 h for one person on the
    task in a day). Show it to the user first.
    """
    task_id = object_id(task_id, "task", "search_tasks")
    if not 0 < minutes <= 24 * 60:
        raise ToolError("minutes must be between 1 and 1440")
    when = iso_date(day, "day") if day else date.today().isoformat()
    lookups = get_lookups()
    record = lookups.person(person) if person else None
    task = fetch_task_full(task_id)
    user = current_user()
    person_id = record["id"] if record else user["id"]
    name = (record or user).get("full_name") or person_id
    plan = Plan(
        "log_time",
        would=f"Log {minutes} min on {task_label(task)} for {name} on {when}",
        message=f"Logged {minutes} min on {when}.",
    )
    plan.request("POST", f"actions/tasks/{task_id}/time-spents/{when}/persons/{person_id}/add", {"duration": minutes})
    that_day = _logged(task_id, person_id, when)
    total = task.get("duration") or 0
    plan.before = {"task_total": total, "person_day": that_day}
    plan.after = {"task_total": total + minutes, "person_day": that_day + minutes}
    if person_id != user["id"]:
        warn_unless_lead(plan, "log time for someone else", user)
    if that_day + minutes > 24 * 60:
        plan.fail(f"{name} would have {that_day + minutes:g} min logged on this task on {when}, over 24 h.")
    if when > date.today().isoformat():
        plan.warnings.append(f"{when} is in the future.")
    return send_or_preview(plan, task_id, dry_run)
