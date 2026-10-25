"""Task dates and estimates."""

from datetime import date

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.formatters import day
from kitsu_mcp.kitsu.models import DryRunResult, WriteResult
from kitsu_mcp.kitsu.plans import Plan
from kitsu_mcp.kitsu.validation import iso_date, object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import (
    OVERWRITE,
    WRITE,
    fetch_task_full,
    send_or_preview,
    task_label,
    warn_unless_lead,
)


@tool(annotations=OVERWRITE, tags=WRITE)
def update_task_schedule(
    task_id: str,
    start_date: str | None = None,
    due_date: str | None = None,
    estimation_minutes: float | None = None,
    dry_run: bool = False,
) -> WriteResult | DryRunResult:
    """Set a task's start date, due date (YYYY-MM-DD) and/or estimate (minutes). Omitted fields are unchanged.

    dry_run=True: check everything with reads only and return the plan instead of writing: `would`, the
    exact `requests`, the fields `before`/`after` and `warnings`; verdict "would_fail" gives the `reason` the
    real call would be refused (a start date after the due date). Show it to the user first.
    """
    task_id = object_id(task_id, "task", "search_tasks")
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
    task = fetch_task_full(task_id)
    current = {"start_date": day(task.get("start_date")), "due_date": day(task.get("due_date"))}
    current["estimation"] = task.get("estimation")
    shown = ", ".join(f"{k} to {v:g}" if isinstance(v, float) else f"{k} to {v}" for k, v in changes.items())
    plan = Plan(
        "update_task_schedule", would=f"Set {shown} on {task_label(task)}", message=f"Updated {', '.join(changes)}."
    )
    plan.request("PUT", f"data/tasks/{task_id}", changes)
    plan.before = {k: current[k] for k in changes}
    plan.after = dict(changes)
    warn_unless_lead(plan, "change task schedules")
    start, due = {**current, **changes}["start_date"], {**current, **changes}["due_date"]
    if ({"start_date", "due_date"} & set(changes)) and start and due and start > due:
        plan.fail(f"The start date ({start}) would be after the due date ({due}).")
    if "due_date" in changes and changes["due_date"] < date.today().isoformat():
        plan.warnings.append(f"The due date {changes['due_date']} is in the past: the task will show as overdue.")
    if plan.before == plan.after:
        plan.warnings.append("These are the current values: nothing changes.")
    return send_or_preview(plan, task_id, dry_run)
