"""Assign people to tasks, or take them off."""

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, WriteResult
from kitsu_mcp.kitsu.plans import Plan
from kitsu_mcp.kitsu.validation import object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import (
    ADDITIVE_IDEMPOTENT,
    WRITE,
    fetch_task_full,
    send_or_preview,
    task_label,
    warn_unless_lead,
    written_task_result,
)


# Takes people off a task with remove=True.
@tool(annotations={**ADDITIVE_IDEMPOTENT, "destructiveHint": True}, tags=WRITE)
def assign_task(task_id: str, person: str, remove: bool = False, dry_run: bool = False) -> WriteResult | DryRunResult:
    """Add a person (name, email or ID) to a task's assignees, or take them off it with remove=True.

    dry_run=True: check everything with reads only and return the plan instead of writing: `would`, the
    exact `requests`, the assignees `before`/`after` and `warnings`; verdict "would_fail" gives the `reason`
    the real call would be refused (an inactive person). Show it to the user first.
    """
    task_id = object_id(task_id, "task", "search_tasks")
    record = get_lookups().person(person)
    task = fetch_task_full(task_id)
    name = record.get("full_name") or record["id"]
    people = task.get("persons") or []
    current = [p.get("full_name") or p["id"] for p in people]
    assigned = record["id"] in (task.get("assignees") or [])
    plan = Plan("assign_task", would="")
    plan.before = {"assignees": current}
    warn_unless_lead(plan, "unassign tasks" if remove else "assign tasks")
    if remove:
        if not assigned:
            plan.would = f"Nothing: {name} is not assigned to {task_label(task)}"
            plan.warnings.append(f"{name} is not assigned: no request is sent.")
            plan.after, plan.message = plan.before, f"{name} was not assigned; nothing changed."
            return send_or_preview(plan, task_id, dry_run)
        plan.would, plan.message = f"Unassign {name} from {task_label(task)}", f"Unassigned {name}."
        plan.request("PUT", "actions/tasks/clear-assignation", {"task_ids": [task_id], "person_id": record["id"]})
        plan.after = {"assignees": [p.get("full_name") or p["id"] for p in people if p["id"] != record["id"]]}
        if dry_run:
            return plan.preview()
        # Zou skips tasks the caller may not unassign (another department) and answers with those it changed.
        if task_id not in (plan.send()[0] or []):
            raise ToolError(f"Kitsu did not unassign {name}: your role or department may not allow it")
        return written_task_result(plan.message, task_id)
    plan.would, plan.message = f"Assign {name} to {task_label(task)}", f"Assigned {name}."
    plan.request("PUT", f"actions/persons/{record['id']}/assign", {"task_ids": [task_id]})
    plan.after = {"assignees": current if assigned else [*current, name]}
    if not record.get("active", True):
        plan.fail(f"{name} is an inactive Kitsu account.")
    if assigned:
        plan.warnings.append(f"{name} is already assigned: nothing changes.")
    return send_or_preview(plan, task_id, dry_run)
