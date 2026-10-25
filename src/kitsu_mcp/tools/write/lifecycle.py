"""Task lifecycle: start a task, submit it for review, publish a preview, act on many tasks at once, and edit or
delete comments.

Routes follow gazu (what kitsu-cli calls) and were checked on a throwaway Zou: publishing is a comment with a
status, a preview record attached to it (`.../comments/<id>/add-preview`), then the file upload
(`pictures/preview-files/<id>`); deleting a comment deletes its previews too.
"""

import os
from typing import Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, EntityWriteResult, WriteResult
from kitsu_mcp.kitsu.plans import Plan, current_user
from kitsu_mcp.kitsu.validation import object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.server.http import over_http
from kitsu_mcp.tools.write.common import (
    ADDITIVE,
    MANAGE,
    WRITE,
    fetch_task_full,
    plan_task_comment,
    require_confirm,
    send_entity_write,
    send_or_preview,
    task_label,
    warn_unless_lead,
)

PRODUCTION = WRITE | {"production"}
MAX_BATCH = 100
_PREVIEW_TYPES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".exr",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".pdf",
    ".obj",
    ".glb",
    ".gltf",
    ".fbx",
    ".zip",
}


def _status_of_role(role: str) -> dict:
    """The status the studio uses for a role (e.g. waiting_review), preferring Kitsu's usual short names."""
    lookups = get_lookups()
    usual = {"wip": ("wip",), "waiting_review": ("wfa", "review", "wfr")}.get(role, ())
    candidates = [
        s for s in lookups.index("task_statuses").values() if not s.get("archived") and lookups.role(s["id"]) == role
    ]
    if not candidates:
        raise ToolError(f"No task status has the role {role} here; pass status explicitly (list_task_statuses)")
    candidates.sort(key=lambda s: (s["short_name"].lower() not in usual, s["short_name"]))
    return candidates[0]


@tool(annotations=ADDITIVE, tags=PRODUCTION)
def task_action(
    action: Literal["start", "submit_for_review"],
    task_id: str,
    comment: str = "",
    status: str | None = None,
    dry_run: bool = False,
) -> WriteResult | DryRunResult:
    """Start a task, or submit it for review: a comment that moves it to the matching status.

    start: the studio's work-in-progress status (wip). submit_for_review: its waiting-for-review status (wfa or
    the studio's own; list_task_statuses shows roles). status (short name) overrides the choice. To attach a
    file when submitting, use publish_preview instead. dry_run=True: show the plan (status before/after) without
    writing; show it to the user first.
    """
    role = "wip" if action == "start" else "waiting_review"
    target = status or _status_of_role(role)["short_name"]
    plan, task, previous, new = plan_task_comment("task_action", task_id, comment, target)
    verb = "Start" if action == "start" else "Submit for review"
    plan.would = f"{verb} {task_label(task)}: {previous} -> {new}" + (" with a comment" if comment.strip() else "")
    plan.message = f"{verb}: status {previous} -> {new}."
    if previous == new:
        plan.warnings.append(f"The status is already {new}: only a comment is added.")
    return send_or_preview(plan, task["id"], dry_run)


# `local`: it reads a file on the server's machine, so the hosted server hides it (as it does downloads).
@tool(annotations=ADDITIVE, tags=PRODUCTION | {"local"})
def publish_preview(
    task_id: str,
    file_path: str,
    status: str | None = None,
    comment: str = "",
    set_main: bool = False,
    dry_run: bool = False,
) -> EntityWriteResult | DryRunResult:
    """Publish a file (image, movie, PDF, ...) on a task, as Kitsu's "publish revision": a comment with a status
    and the file attached as the task's next revision.

    file_path: a file on the machine running the server (not available on a hosted server). status: short name
    (default: the studio's waiting-for-review status). set_main: also make it the entity's thumbnail. Kitsu
    builds the playable versions in the background (the preview shows "processing" for a while).
    dry_run=True: check the file and show the plan (the three requests) without sending; show it to the user
    first.
    """
    if over_http():
        raise ToolError("publish_preview reads a local file, so it is not available on the hosted server")
    path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(path):
        raise ToolError(f"No file at {path}")
    extension = os.path.splitext(path)[1].lower()
    target = status or _status_of_role("waiting_review")["short_name"]
    plan, task, previous, new = plan_task_comment("publish_preview", task_id, comment, target)
    previews = get_client().get(f"data/tasks/{task['id']}/previews")
    revision = max((p.get("revision") or 0 for p in previews), default=0) + 1
    # The comment comes first (request 0); its ID, then the preview's (request 1), fill the later paths.
    plan.request("POST", f"actions/tasks/{task['id']}/comments/{{0.id}}/add-preview", {})
    plan.request("UPLOAD", "pictures/preview-files/{1.id}", {"file": path})
    if set_main:
        plan.request("PUT", "actions/preview-files/{1.id}/set-main-preview", {})
    size_mb = os.path.getsize(path) / 2**20
    plan.would = (
        f"Publish {os.path.basename(path)} ({size_mb:.1f} MB) as revision {revision} of {task_label(task)}"
        f", status {previous} -> {new}" + (", as the thumbnail" if set_main else "")
    )
    plan.message = f"Published revision {revision}; status {previous} -> {new}."
    plan.before["revision"] = revision - 1
    plan.after["revision"] = revision
    if extension not in _PREVIEW_TYPES:
        plan.warnings.append(f"Kitsu may not preview {extension or 'files without an extension'}.")
    if size_mb > 500:
        plan.warnings.append(f"{size_mb:.0f} MB is large: the upload may take a while.")
    return send_entity_write(plan, dry_run, reload=lambda answers: answers[2])  # the upload's answer: up to date


def _task_ids(task_ids: list[str]) -> list[str]:
    if not task_ids:
        raise ToolError("Pass task_ids (search_tasks finds them)")
    if len(task_ids) > MAX_BATCH:
        raise ToolError(f"At most {MAX_BATCH} tasks per call; split the list")
    return list(dict.fromkeys(object_id(t, "task", "search_tasks") for t in task_ids))


@tool(annotations=MANAGE, tags=PRODUCTION)
def batch_tasks(
    action: Literal["status", "assign", "unassign", "priority", "delete"],
    task_ids: list[str],
    status: str | None = None,
    comment: str = "",
    person: str | None = None,
    priority: int | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> EntityWriteResult | DryRunResult:
    """Act on many tasks at once (at most 100).

    status: set every task to status (short name), with an optional comment on each. assign / unassign: person
    (name, email or ID); unassign without person clears every assignee. priority: 0 (normal) to 3 (emergency).
    delete: delete the tasks with their comments and previews; needs confirm=True. Tasks already in the
    requested state are skipped. dry_run=True: show the plan without writing; show it to the user first.
    """
    ids = _task_ids(task_ids)
    require_confirm(action, confirm, dry_run, f"{len(ids)} task(s)")
    lookups = get_lookups()
    tasks = {t: fetch_task_full(t) for t in ids}
    labels = {t: task_label(task) for t, task in tasks.items()}
    plan = Plan("batch_tasks", would="")
    changed: list[str] = []
    if action == "status":
        if not status:
            raise ToolError("status needs status (a short name)")
        record = lookups.task_status(status)
        if record.get("archived"):
            plan.fail(f"Status {record['short_name']} is archived in Kitsu; pick an active one.")
        for t, task in tasks.items():
            if task["task_status_id"] == record["id"] and not comment.strip():
                continue
            plan.request("POST", f"actions/tasks/{t}/comment", {"task_status_id": record["id"], "comment": comment})
            changed.append(t)
        plan.would = f"Set {len(changed)} task(s) to {record['short_name']}"
        plan.message = f"Set {len(changed)} task(s) to {record['short_name']}."
    elif action == "assign":
        if not person:
            raise ToolError("assign needs person")
        who = lookups.person(person)
        name = who.get("full_name") or who["id"]
        changed = [t for t, task in tasks.items() if who["id"] not in (task.get("assignees") or [])]
        if not who.get("active", True):
            plan.fail(f"{name} is an inactive Kitsu account.")
        if changed:
            plan.request("PUT", f"actions/persons/{who['id']}/assign", {"task_ids": changed})
        plan.would, plan.message = (
            f"Assign {name} to {len(changed)} task(s)",
            f"Assigned {name}: {len(changed)} task(s).",
        )
        warn_unless_lead(plan, "assign tasks")
    elif action == "unassign":
        who = lookups.person(person) if person else None
        name = who.get("full_name") or who["id"] if who else "everyone"

        def assigned(task: dict) -> bool:
            people = task.get("assignees") or []
            return who["id"] in people if who else bool(people)

        changed = [t for t, task in tasks.items() if assigned(task)]
        if changed:
            payload: dict = {"task_ids": changed}
            if who:
                payload["person_id"] = who["id"]
            plan.request("PUT", "actions/tasks/clear-assignation", payload)
        plan.would = f"Unassign {name} from {len(changed)} task(s)"
        plan.message = f"Unassigned {name}: {len(changed)} task(s)."
        warn_unless_lead(plan, "unassign tasks")
    elif action == "priority":
        if priority is None or not 0 <= priority <= 3:
            raise ToolError("priority needs priority between 0 (normal) and 3 (emergency)")
        for t, task in tasks.items():
            if (task.get("priority") or 0) != priority:
                plan.request("PUT", f"data/tasks/{t}", {"priority": priority})
                changed.append(t)
        plan.would = f"Set priority {priority} on {len(changed)} task(s)"
        plan.message = f"Priority {priority} set on {len(changed)} task(s)."
    else:
        projects = {task["project_id"] for task in tasks.values()}
        for project_id in projects:
            in_project = [t for t, task in tasks.items() if task["project_id"] == project_id]
            plan.request("POST", f"actions/projects/{project_id}/delete-tasks", in_project)  # Zou wants a bare array
            changed += in_project
        plan.would = f"Delete {len(changed)} task(s) with their comments, previews and time logs"
        plan.message = f"Deleted {len(changed)} task(s)."
        warn_unless_lead(plan, "delete tasks")
    skipped = [labels[t] for t in ids if t not in changed]
    plan.before = {"tasks": len(ids)}
    plan.after = {"changed": [labels[t] for t in changed]}
    if skipped:
        plan.warnings.append(
            f"Skipped {len(skipped)} already as requested: {', '.join(skipped[:10])}"
            + (" ..." if len(skipped) > 10 else "")
        )
    if not changed:
        plan.warnings.append("Nothing to change: no request is sent.")
    return send_entity_write(plan, dry_run, reload=lambda _: None)


@tool(annotations=MANAGE, tags=PRODUCTION)
def manage_comment(
    action: Literal["edit", "delete", "delete_reply"],
    task_id: str,
    comment_id: str,
    text: str | None = None,
    reply_id: str | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> EntityWriteResult | DryRunResult:
    """Edit or delete a comment on a task, or delete one of its replies (IDs from get_task).

    edit: text, the new text. delete: removes the comment and the previews attached to it (a published
    revision); needs confirm=True. delete_reply: reply_id. Kitsu usually lets people change only their own
    comments unless they are admins. dry_run=True: show the plan without writing; show it to the user first.
    """
    task_id = object_id(task_id, "task", "search_tasks")
    comment_id = object_id(comment_id, "comment", "get_task")
    require_confirm("delete" if action != "edit" else "edit", confirm, dry_run, "a comment")
    task = fetch_task_full(task_id)
    record = next((c for c in get_client().get(f"data/tasks/{task_id}/comments") if c["id"] == comment_id), None)
    if record is None:
        raise ToolError(f"Comment {comment_id} is not on task {task_id}; get_task lists its comments")
    author = (record.get("person") or {}).get("full_name") or "someone"
    plan = Plan("manage_comment", would="")
    user = current_user()
    if (record.get("person") or {}).get("id") != user["id"] and user.get("role") != "admin":
        plan.warnings.append(f"Kitsu may refuse: this is {author}'s comment and your role is {user.get('role')}.")
    if action == "edit":
        if not text or not text.strip():
            raise ToolError("edit needs text")
        plan.request("PUT", f"data/comments/{comment_id}", {"text": text})
        plan.would = f"Edit {author}'s comment on {task_label(task)}"
        plan.message = "Comment edited."
        plan.before, plan.after = {"text": record.get("text")}, {"text": text}
    elif action == "delete":
        previews = record.get("previews") or []
        plan.request("DELETE", f"data/comments/{comment_id}")
        plan.would = f"Delete {author}'s comment on {task_label(task)}"
        plan.message = "Comment deleted."
        plan.before = {"previews": len(previews), "replies": len(record.get("replies") or [])}
        plan.after = {"exists": False}
        if previews:
            plan.warnings.append(f"It carries {len(previews)} preview(s): Kitsu deletes them with the comment.")
    else:
        if not reply_id:
            raise ToolError("delete_reply needs reply_id")
        reply = next((r for r in record.get("replies") or [] if r.get("id") == reply_id), None)
        if reply is None:
            raise ToolError(f"Reply {reply_id} is not on that comment; get_task lists replies")
        plan.request("DELETE", f"data/tasks/{task_id}/comments/{comment_id}/reply/{reply_id}")
        plan.would = f"Delete a reply on {author}'s comment"
        plan.message = "Reply deleted."
        plan.before, plan.after = (
            {"replies": len(record.get("replies") or [])},
            {"replies": len(record.get("replies") or []) - 1},
        )
    return send_entity_write(plan, dry_run, reload=lambda _: None)
