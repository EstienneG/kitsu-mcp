"""What the write tools share: their annotations and tag, task loading and the plan/result helpers.

Each tool builds a `Plan` (kitsu/plans.py) with reads only: the exact requests, the fields they change and the
checks. dry_run=True returns it; otherwise the plan is sent, so a dry run always shows the real call.
"""

from collections.abc import Callable
from typing import Any

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.formatters import task_detail
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, EntityWriteResult, WriteResult
from kitsu_mcp.kitsu.plans import ARTIST_ROLES, LEAD_ROLES, Plan, current_user
from kitsu_mcp.kitsu.validation import object_id

WRITE = {"write"}
# Each call adds something (a comment, logged time): repeating it duplicates the effect.
ADDITIVE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
# Adds an assignee; repeating it is harmless.
ADDITIVE_IDEMPOTENT = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
# Replaces existing values.
OVERWRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}
# Creates, changes or deletes records depending on `action`: clients should always ask first.
MANAGE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}

# Fields worth echoing back after a write: enough to recognise the record and chain the next call.
_KEY_FIELDS = (
    "id",
    "name",
    "short_name",
    "type",
    "project_id",
    "parent_id",
    "entity_type_id",
    "task_type_id",
    "task_status_id",
    "description",
    "nb_frames",
    "data",
    "assignees",
    "for_entity",
    "archived",
)


def key_fields(record: dict | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    return {k: record[k] for k in _KEY_FIELDS if record.get(k) not in (None, "", [], {})}


def require_confirm(action: str, confirm: bool, dry_run: bool, what: str) -> None:
    """Deletes need confirm=True, so an agent cannot delete by picking the wrong action; a dry run never does."""
    if action == "delete" and not confirm and not dry_run:
        raise ToolError(
            f"Deleting {what} cannot be undone from here: call again with dry_run=True to see what it removes, "
            "then with confirm=True once the user agreed"
        )


def send_entity_write(
    plan: Plan,
    dry_run: bool,
    reload: Callable[[list[Any]], dict | None] | None = None,
    url: Callable[[dict], str | None] | None = None,
) -> EntityWriteResult | DryRunResult:
    """Preview the plan, or send it and report the record. `reload(answers)` returns the record as it is now
    (default: the last answer); a failing reload must not make the write look failed."""
    if dry_run:
        return plan.preview()
    answers = plan.send()
    try:
        record = reload(answers) if reload else (answers[-1] if answers else None)
    except Exception as error:  # noqa: BLE001 - the write succeeded; only the read-back failed
        return EntityWriteResult(ok=True, message=f"{plan.message} (Could not read it back: {error})")
    fields = key_fields(record)
    link = None
    if record and url:
        try:
            link = url(record)
        except Exception:  # noqa: BLE001 - a link is a bonus
            link = None
    return EntityWriteResult(ok=True, message=plan.message, id=(fields or {}).get("id"), entity=fields, url=link)


def fetch_task_full(task_id: str) -> dict:
    return get_client().get(f"data/tasks/{task_id}/full")


def task_label(task: dict) -> str:
    """'SQ010 / SH010 / Animation': which task, for the one-line plan."""
    parts = [(task.get(k) or {}).get("name") for k in ("sequence", "entity", "task_type")]
    return " / ".join(p for p in parts if p) or task["id"]


def send_or_preview(plan: Plan, task_id: str, dry_run: bool) -> WriteResult | DryRunResult:
    """Return the plan (dry run), or send it and report the task as it is now."""
    if dry_run:
        return plan.preview()
    plan.send()
    return written_task_result(plan.message, task_id)


def written_task_result(message: str, task_id: str) -> WriteResult:
    """The write already succeeded: a failing re-read must not make it look failed (and invite a retry)."""
    try:
        task = task_detail(fetch_task_full(task_id))
    except Exception as error:  # noqa: BLE001 - any failure here happens after a successful write
        return WriteResult(ok=True, message=f"{message} (Could not reload the task: {error})", task=None)
    return WriteResult(ok=True, message=message, task=task)


def warn_unless_lead(plan: Plan, action: str, user: dict | None = None) -> None:
    """Kitsu normally keeps assigning, scheduling and logging time for others to admins, managers and
    supervisors. Studios can set this up differently, so it is a warning, not a refusal."""
    role = (user or current_user()).get("role")
    if role not in LEAD_ROLES:
        plan.warnings.append(f"Kitsu may refuse: your role ({role}) usually cannot {action}.")


def plan_task_comment(tool_name: str, task_id: str, text: str, status: str | None) -> tuple[Plan, dict, str, str]:
    """A comment, with an optional status change. Kitsu requires a status on every comment, so it defaults to
    the current one. Returns the plan, the task, and the previous and new status short names."""
    task_id = object_id(task_id, "task", "search_tasks")
    lookups = get_lookups()
    task = fetch_task_full(task_id)
    status_id = lookups.task_status(status)["id"] if status else task["task_status_id"]
    record = lookups.index("task_statuses").get(status_id, {})
    previous = task["task_status"]["short_name"]
    new = record.get("short_name") or status_id
    plan = Plan(tool_name, would="")
    plan.request("POST", f"actions/tasks/{task_id}/comment", {"task_status_id": status_id, "comment": text})
    plan.before, plan.after = {"status": previous}, {"status": new}
    if new != previous:
        role = current_user().get("role")
        if role in ARTIST_ROLES and not record.get("is_artist_allowed"):
            plan.warnings.append(f"Kitsu may refuse: status {new} is not open to artists, and your role is {role}.")
        if role == "client" and not record.get("is_client_allowed"):
            plan.warnings.append(f"Kitsu may refuse: status {new} is not open to clients.")
        if record.get("archived"):
            plan.fail(f"Status {new} is archived in Kitsu; pick an active one (list_task_statuses).")
        if lookups.role(status_id) in ("done", "omitted"):
            plan.warnings.append(f"This closes the task (status role {lookups.role(status_id)}).")
    return plan, task, previous, new
