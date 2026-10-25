"""Comments: post one (or a reply), change a status, acknowledge a comment."""

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.models import DryRunResult, WriteResult
from kitsu_mcp.kitsu.plans import Plan, current_user
from kitsu_mcp.kitsu.validation import object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import (
    ADDITIVE,
    ADDITIVE_IDEMPOTENT,
    WRITE,
    fetch_task_full,
    plan_task_comment,
    send_or_preview,
    task_label,
)


@tool(annotations=ADDITIVE, tags=WRITE)
def add_comment(
    task_id: str,
    text: str,
    status: str | None = None,
    reply_to: str | None = None,
    dry_run: bool = False,
) -> WriteResult | DryRunResult:
    """Post a comment on a task as the logged-in user, optionally changing its status (short name).

    reply_to: a comment ID (from get_task or my_notifications) to reply to it instead; a reply never
    changes the status, so it does not take one.
    dry_run=True: check everything with reads only and return the plan instead of posting: `would`, the
    exact `requests`, `before`/`after` and `warnings`; verdict "would_fail" gives the `reason` the real call
    would be refused (e.g. an archived status). Show it to the user before writing.
    """
    if not text.strip():
        raise ToolError("Comment text is empty; use set_task_status to change the status without a comment")
    if reply_to is not None:
        if status is not None:
            raise ToolError("A reply cannot change the status: leave status out, or post a comment instead")
        return _reply(task_id, reply_to, text, dry_run)
    plan, task, previous, new = plan_task_comment("add_comment", task_id, text, status)
    changed = new != previous
    status_change = f" and change its status from {previous} to {new}" if changed else ""
    plan.would = f"Comment on {task_label(task)}{status_change}"
    plan.message = f"Comment posted{f'; status set to {new}' if changed else ''}."
    return send_or_preview(plan, task["id"], dry_run)


@tool(annotations={**ADDITIVE, "destructiveHint": True}, tags=WRITE)
def set_task_status(task_id: str, status: str, comment: str = "", dry_run: bool = False) -> WriteResult | DryRunResult:
    """Change a task's status (short name, e.g. wip, wfa, done), with an optional comment.

    Kitsu records every status change as a comment, so each call adds one to the task.
    dry_run=True: check everything with reads only and return the plan instead of writing: `would`, the
    exact `requests`, `before`/`after` status and `warnings`; verdict "would_fail" gives the `reason` the
    real call would be refused (e.g. an archived status). Show it to the user first.
    """
    plan, task, previous, new = plan_task_comment("set_task_status", task_id, comment, status)
    if previous == new:
        plan.would = f"Comment on {task_label(task)}; its status is already {new}"
        plan.warnings.append(f"The status is already {new}: only a comment is added.")
        plan.message = f"Status was already {new}; comment posted."
    else:
        plan.would = f"Change {task_label(task)} from {previous} to {new}"
        plan.message = f"Status changed from {previous} to {new}."
    return send_or_preview(plan, task["id"], dry_run)


def _comment(task_id: str, comment_id: str) -> dict:
    comment_id = object_id(comment_id, "comment", "get_task")
    for record in get_client().get(f"data/tasks/{task_id}/comments"):
        if record.get("id") == comment_id:
            return record
    raise ToolError(f"Comment {comment_id} is not on task {task_id}; get_task lists the task's comments and their IDs")


def _excerpt(text: str | None) -> str:
    text = " ".join((text or "").split())
    return f'"{text[:60]}{"..." if len(text) > 60 else ""}"' if text else "(no text)"


def _reply(task_id: str, comment_id: str, text: str, dry_run: bool) -> WriteResult | DryRunResult:
    task_id = object_id(task_id, "task", "search_tasks")
    task = fetch_task_full(task_id)
    record = _comment(task_id, comment_id)
    author = (record.get("person") or {}).get("full_name") or "someone"
    plan = Plan(
        "add_comment",
        would=f"Reply on {task_label(task)} to {author}'s comment {_excerpt(record.get('text'))}",
        message="Reply posted.",
    )
    plan.request("POST", f"data/tasks/{task_id}/comments/{record['id']}/reply", {"text": text})
    plan.before = {"replies": len(record.get("replies") or [])}
    plan.after = {"replies": len(record.get("replies") or []) + 1}
    return send_or_preview(plan, task_id, dry_run)


@tool(annotations=ADDITIVE_IDEMPOTENT, tags=WRITE)
def acknowledge_comment(task_id: str, comment_id: str, dry_run: bool = False) -> WriteResult | DryRunResult:
    """Acknowledge a comment on a task as the logged-in user ("seen", as with Kitsu's acknowledge button).
    Does nothing if the user already acknowledged it.

    dry_run=True: check everything with reads only and return the plan instead of writing. Show it to the
    user first.
    """
    task_id = object_id(task_id, "task", "search_tasks")
    task = fetch_task_full(task_id)
    record = _comment(task_id, comment_id)
    user = current_user()
    acknowledged = record.get("acknowledgements") or []
    plan = Plan(
        "acknowledge_comment",
        would=f"Acknowledge the comment {_excerpt(record.get('text'))} on {task_label(task)}",
        message="Comment acknowledged.",
    )
    plan.before = {"acknowledged": user["id"] in acknowledged}
    plan.after = {"acknowledged": True}
    if user["id"] in acknowledged:
        # Zou's route toggles: sending it again would remove the acknowledgement.
        plan.would = f"Nothing: you already acknowledged this comment on {task_label(task)}"
        plan.warnings.append("Already acknowledged: no request is sent.")
        plan.message = "Already acknowledged; nothing changed."
    else:
        plan.request("POST", f"data/tasks/{task_id}/comments/{record['id']}/ack", {})
    return send_or_preview(plan, task_id, dry_run)
