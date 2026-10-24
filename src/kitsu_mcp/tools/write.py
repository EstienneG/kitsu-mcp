"""Tools that modify Kitsu. Registered disabled; `main()` enables them when KITSU_ALLOW_WRITE=true.

Each tool builds a `Plan` (plans.py) with reads only: the exact requests, the fields they change and the
checks. dry_run=True returns it; otherwise the plan is sent, so a dry run always shows the real call.
"""

from datetime import date
from typing import Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.app import tool
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import day, task_detail
from kitsu_mcp.lookups import check_names, get_lookups
from kitsu_mcp.models import DryRunResult, PlaylistEntry, PlaylistWriteResult, SkippedEntry, WriteResult
from kitsu_mcp.plans import ARTIST_ROLES, LEAD_ROLES, PartialSendError, Plan, current_user
from kitsu_mcp.tools.previews import playlist_detail, project_playlists
from kitsu_mcp.validation import iso_date, object_id
from kitsu_mcp.video import is_broken

WRITE = {"write"}
# Each call adds something (a comment, logged time): repeating it duplicates the effect.
ADDITIVE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
# Adds an assignee; repeating it is harmless.
ADDITIVE_IDEMPOTENT = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
# Replaces existing values.
OVERWRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}


def _task(task_id: str) -> dict:
    return get_client().get(f"data/tasks/{task_id}/full")


def _label(task: dict) -> str:
    """'SQ010 / SH010 / Animation': which task, for the one-line plan."""
    parts = [(task.get(k) or {}).get("name") for k in ("sequence", "entity", "task_type")]
    return " / ".join(p for p in parts if p) or task["id"]


def _finish(plan: Plan, task_id: str, dry_run: bool) -> WriteResult | DryRunResult:
    """Return the plan (dry run), or send it and report the task as it is now."""
    if dry_run:
        return plan.preview()
    plan.send()
    return _result(plan.message, task_id)


def _result(message: str, task_id: str) -> WriteResult:
    """The write already succeeded: a failing re-read must not make it look failed (and invite a retry)."""
    try:
        task = task_detail(_task(task_id))
    except Exception as error:  # noqa: BLE001 - any failure here happens after a successful write
        return WriteResult(ok=True, message=f"{message} (Could not reload the task: {error})", task=None)
    return WriteResult(ok=True, message=message, task=task)


def _check_lead(plan: Plan, action: str, user: dict | None = None) -> None:
    """Kitsu normally keeps assigning, scheduling and logging time for others to admins, managers and
    supervisors. Studios can set this up differently, so it is a warning, not a refusal."""
    role = (user or current_user()).get("role")
    if role not in LEAD_ROLES:
        plan.warnings.append(f"Kitsu may refuse: your role ({role}) usually cannot {action}.")


def _plan_comment(tool_name: str, task_id: str, text: str, status: str | None) -> tuple[Plan, dict, str, str]:
    """A comment, with an optional status change. Kitsu requires a status on every comment, so it defaults to
    the current one. Returns the plan, the task, and the previous and new status short names."""
    task_id = object_id(task_id, "task", "search_tasks")
    lookups = get_lookups()
    task = _task(task_id)
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


@tool(annotations=ADDITIVE, tags=WRITE)
def add_comment(
    task_id: str, text: str, status: str | None = None, dry_run: bool = False
) -> WriteResult | DryRunResult:
    """Post a comment on a task as the logged-in user, optionally changing its status (short name).

    dry_run=True: check everything with reads only and return the plan instead of posting: `would`, the
    exact `requests`, `before`/`after` and `warnings`; verdict "would_fail" gives the `reason` the real call
    would be refused (e.g. an archived status). Show it to the user before writing.
    """
    if not text.strip():
        raise ToolError("Comment text is empty; use set_task_status to change the status without a comment")
    plan, task, previous, new = _plan_comment("add_comment", task_id, text, status)
    changed = new != previous
    plan.would = f"Comment on {_label(task)}" + (f" and change its status from {previous} to {new}" if changed else "")
    plan.message = f"Comment posted{f'; status set to {new}' if changed else ''}."
    return _finish(plan, task["id"], dry_run)


@tool(annotations={**ADDITIVE, "destructiveHint": True}, tags=WRITE)
def set_task_status(task_id: str, status: str, comment: str = "", dry_run: bool = False) -> WriteResult | DryRunResult:
    """Change a task's status (short name, e.g. wip, wfa, done), with an optional comment.

    Kitsu records every status change as a comment, so each call adds one to the task.
    dry_run=True: check everything with reads only and return the plan instead of writing: `would`, the
    exact `requests`, `before`/`after` status and `warnings`; verdict "would_fail" gives the `reason` the
    real call would be refused (e.g. an archived status). Show it to the user first.
    """
    plan, task, previous, new = _plan_comment("set_task_status", task_id, comment, status)
    if previous == new:
        plan.would = f"Comment on {_label(task)}; its status is already {new}"
        plan.warnings.append(f"The status is already {new}: only a comment is added.")
        plan.message = f"Status was already {new}; comment posted."
    else:
        plan.would = f"Change {_label(task)} from {previous} to {new}"
        plan.message = f"Status changed from {previous} to {new}."
    return _finish(plan, task["id"], dry_run)


@tool(annotations=ADDITIVE_IDEMPOTENT, tags=WRITE)
def assign_task(task_id: str, person: str, dry_run: bool = False) -> WriteResult | DryRunResult:
    """Add a person (name, email or ID) to a task's assignees.

    dry_run=True: check everything with reads only and return the plan instead of writing: `would`, the
    exact `requests`, the assignees `before`/`after` and `warnings`; verdict "would_fail" gives the `reason`
    the real call would be refused (an inactive person). Show it to the user first.
    """
    task_id = object_id(task_id, "task", "search_tasks")
    record = get_lookups().person(person)
    task = _task(task_id)
    name = record.get("full_name") or record["id"]
    current = [p.get("full_name") or p["id"] for p in task.get("persons") or []]
    plan = Plan("assign_task", would=f"Assign {name} to {_label(task)}", message=f"Assigned {name}.")
    plan.request("PUT", f"actions/persons/{record['id']}/assign", {"task_ids": [task_id]})
    plan.before = {"assignees": current}
    plan.after = {"assignees": current if record["id"] in task.get("assignees", []) else [*current, name]}
    _check_lead(plan, "assign tasks")
    if not record.get("active", True):
        plan.fail(f"{name} is an inactive Kitsu account.")
    if record["id"] in (task.get("assignees") or []):
        plan.warnings.append(f"{name} is already assigned: nothing changes.")
    return _finish(plan, task_id, dry_run)


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
    task = _task(task_id)
    current = {"start_date": day(task.get("start_date")), "due_date": day(task.get("due_date"))}
    current["estimation"] = task.get("estimation")
    shown = ", ".join(f"{k} to {v:g}" if isinstance(v, float) else f"{k} to {v}" for k, v in changes.items())
    plan = Plan(
        "update_task_schedule", would=f"Set {shown} on {_label(task)}", message=f"Updated {', '.join(changes)}."
    )
    plan.request("PUT", f"data/tasks/{task_id}", changes)
    plan.before = {k: current[k] for k in changes}
    plan.after = dict(changes)
    _check_lead(plan, "change task schedules")
    start, due = {**current, **changes}["start_date"], {**current, **changes}["due_date"]
    if ({"start_date", "due_date"} & set(changes)) and start and due and start > due:
        plan.fail(f"The start date ({start}) would be after the due date ({due}).")
    if "due_date" in changes and changes["due_date"] < date.today().isoformat():
        plan.warnings.append(f"The due date {changes['due_date']} is in the past: the task will show as overdue.")
    if plan.before == plan.after:
        plan.warnings.append("These are the current values: nothing changes.")
    return _finish(plan, task_id, dry_run)


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
    task = _task(task_id)
    user = current_user()
    person_id = record["id"] if record else user["id"]
    name = (record or user).get("full_name") or person_id
    plan = Plan(
        "log_time",
        would=f"Log {minutes} min on {_label(task)} for {name} on {when}",
        message=f"Logged {minutes} min on {when}.",
    )
    plan.request("POST", f"actions/tasks/{task_id}/time-spents/{when}/persons/{person_id}/add", {"duration": minutes})
    that_day = _logged(task_id, person_id, when)
    total = task.get("duration") or 0
    plan.before = {"task_total": total, "person_day": that_day}
    plan.after = {"task_total": total + minutes, "person_day": that_day + minutes}
    if person_id != user["id"]:
        _check_lead(plan, "log time for someone else", user)
    if that_day + minutes > 24 * 60:
        plan.fail(f"{name} would have {that_day + minutes:g} min logged on this task on {when}, over 24 h.")
    if when > date.today().isoformat():
        plan.warnings.append(f"{when} is in the future.")
    return _finish(plan, task_id, dry_run)


MAX_PLAYLIST_ADDS = 50


@tool(annotations=ADDITIVE, tags=WRITE)
def create_playlist(
    project: str,
    name: str,
    for_entity: Literal["shot", "asset"],
    episode: str | None = None,
    task_type: str | None = None,
    for_client: bool = False,
    dry_run: bool = False,
) -> PlaylistWriteResult | DryRunResult:
    """Create an empty review playlist of shots or assets in a project; fill it with add_to_playlist.

    project: name or ID. name: must not already be used by another playlist of the same episode (or of
    the project, without episode); the error gives the existing one's ID. episode: name or ID, required
    for shot playlists of TV shows that have episodes, not allowed in projects without episodes.
    task_type: name, shown as the playlist's task type in Kitsu. for_client: share it with client
    accounts. Returns the new playlist (`playlist.id` is what add_to_playlist takes).

    dry_run=True: check everything with reads only and return the plan instead of creating it: `would`
    and the exact `requests`. Show it to the user before writing.
    """
    lookups = get_lookups()
    client = get_client()
    record = lookups.project(project)
    name = name.strip()
    if not name:
        raise ToolError("Playlist name is empty")
    episodes = client.get(f"data/projects/{record['id']}/episodes") if record.get("production_type") == "tvshow" else []
    episode_id = None
    if episode is not None:
        if not episodes:
            raise ToolError(f"{record['name']} has no episodes, leave episode out")
        match = [e for e in episodes if episode in (e["id"], e["name"]) or e["name"].lower() == episode.lower()]
        if not match:
            check_names("episode", [episode], {e["name"] for e in episodes})
        episode_id = match[0]["id"]
    elif episodes and for_entity == "shot":
        raise ToolError(f"{record['name']} is a TV show: pass the episode of the shots (list_episodes)")
    task_type_id = lookups.task_type(task_type)["id"] if task_type is not None else None
    for existing in project_playlists(record["id"]):
        if existing.get("episode_id") == episode_id and existing["name"].strip().lower() == name.lower():
            raise ToolError(
                f"{record['name']} already has a playlist named '{existing['name']}'"
                f"{' in this episode' if episode_id else ''} (ID {existing['id']}); "
                "pick another name, or add to it with add_to_playlist"
            )
    data: dict = {
        "name": name,
        "project_id": record["id"],
        "for_entity": for_entity,
        "for_client": for_client,
        "is_for_all": False,
    }
    if episode_id:
        data["episode_id"] = episode_id
    if task_type_id:
        data["task_type_id"] = task_type_id
    message = f"Created playlist '{name}' in {record['name']}."
    plan = Plan("create_playlist", would=f"Create {for_entity} playlist '{name}' in {record['name']}", message=message)
    plan.request("POST", "data/playlists/", data)
    if dry_run:
        return plan.preview()
    raw = plan.send()[0]
    try:
        detail = playlist_detail(raw)
    except Exception as error:  # noqa: BLE001 - the playlist exists: do not invite a retry that duplicates it
        return PlaylistWriteResult(ok=True, message=f"{message} (Could not read it back: {error})", playlist=None)
    return PlaylistWriteResult(ok=True, message=message, playlist=detail)


def _latest_preview(task_id: str) -> dict | None:
    """A task's latest revision's main file (position 1), skipping files Kitsu failed to process."""
    previews = [p for p in get_client().get(f"data/tasks/{task_id}/previews") if not is_broken(p)]
    return min(previews, key=lambda p: (-(p.get("revision") or 0), p.get("position") or 1), default=None)


@tool(annotations=ADDITIVE_IDEMPOTENT, tags=WRITE)
def add_to_playlist(
    playlist_id: str,
    task_ids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    task_type: str | None = None,
    dry_run: bool = False,
) -> PlaylistWriteResult | DryRunResult:
    """Add shots or assets to a playlist (at most 50 per call), each with the preview to review.

    task_ids: tasks (e.g. from search_tasks); each adds its shot or asset with that task's latest
    revision (main file, broken uploads skipped). entity_ids: shots or assets. With task_type (name),
    each gets the latest revision of its task of that type (if it has several, the most recent upload
    among them); without it, the preview Kitsu currently shows for the entity, whatever task it comes
    from. task_type applies to entity_ids only.
    Everything must belong to the playlist's project, match what it holds (shots or assets) and, for a
    shot playlist of an episode, be in that episode; else nothing is added. Entities already in the
    playlist (or repeated in the call), or without a usable preview, are skipped and listed in `skipped`
    with the reason; so a repeated call adds nothing twice. `added` gives each entity with the task type
    and revision it shows.

    dry_run=True: check everything with reads only and return the plan instead of adding: `would`, one
    request per entity that would be added, and a warning per entity that would be skipped. Show it to
    the user before writing.
    """
    task_ids = [object_id(t, "task", "search_tasks") for t in task_ids or []]
    entity_ids = [object_id(e, "entity", "list_shots or list_assets") for e in entity_ids or []]
    if not task_ids and not entity_ids:
        raise ToolError("Nothing to add: pass task_ids and/or entity_ids")
    if len(task_ids) + len(entity_ids) > MAX_PLAYLIST_ADDS:
        raise ToolError(f"At most {MAX_PLAYLIST_ADDS} tasks and entities per call; split the list")
    if task_type is not None and not entity_ids:
        raise ToolError("task_type picks the preview of entity_ids; tasks already say which preview to use")
    client = get_client()
    lookups = get_lookups()
    task_type_id = lookups.task_type(task_type)["id"] if task_type is not None else None
    playlist_id = object_id(playlist_id, "playlist", "list_playlists")
    playlist = client.get(f"data/playlists/{playlist_id}")
    kind = playlist.get("for_entity")
    if kind not in ("shot", "asset"):
        raise ToolError(f"Playlist '{playlist['name']}' holds {kind}s; only shot and asset playlists are supported")
    project_id = playlist["project_id"]
    entities = {e["id"]: e for e in client.get(f"data/{kind}s", params={"project_id": project_id})}
    project_name = lookups.name("projects", project_id) or project_id
    episode_id = playlist.get("episode_id") if kind == "shot" else None
    # Shots point to their sequence (parent_id); the sequence points to its episode.
    episode_of = (
        {s["id"]: s.get("parent_id") for s in client.get(f"data/projects/{project_id}/sequences")} if episode_id else {}
    )

    def check_entity(entity_id: str, ref: str) -> None:
        if entity_id not in entities:
            raise ToolError(
                f"{ref} is not a {kind} of {project_name}, so it cannot go in playlist '{playlist['name']}'; "
                "nothing was added"
            )
        if episode_id and episode_of.get(entities[entity_id].get("parent_id")) != episode_id:
            raise ToolError(
                f"{ref} ({entities[entity_id]['name']}) is not in the episode of playlist '{playlist['name']}'; "
                "nothing was added"
            )

    # Resolve and check everything before the first write, so a bad ID never leaves a half-filled playlist.
    present = {e["entity_id"] for e in playlist.get("shots") or []}
    planned: list[PlaylistEntry] = []
    skipped: list[SkippedEntry] = []

    def plan(ref: str, entity_id: str, preview: dict | None, task_type_id: str | None, missing: str) -> None:
        entity = entities[entity_id]["name"]
        if entity_id in present:
            skipped.append(SkippedEntry(ref=ref, entity=entity, reason="already in the playlist"))
        elif preview is None:
            skipped.append(SkippedEntry(ref=ref, entity=entity, reason=missing))
        else:
            present.add(entity_id)
            planned.append(
                PlaylistEntry(
                    entity_id=entity_id,
                    entity=entity,
                    task_type=lookups.name("task_types", task_type_id),
                    revision=preview.get("revision"),
                    preview_file_id=preview["id"],
                )
            )

    tasks = [_task(t) for t in task_ids]
    for task in tasks:
        check_entity(task["entity_id"], f"Task {task['id']}")
    for entity_id in entity_ids:
        check_entity(entity_id, f"Entity {entity_id}")
    for task in tasks:
        plan(task["id"], task["entity_id"], _latest_preview(task["id"]), task["task_type_id"], "no preview uploaded")
    for entity_id in entity_ids:
        if task_type_id:
            typed = [t for t in client.get(f"data/{kind}s/{entity_id}/tasks") if t["task_type_id"] == task_type_id]
            latest = [p for p in map(_latest_preview, (t["id"] for t in typed)) if p]
            preview = max(latest, key=lambda p: p.get("created_at") or "", default=None)
            missing = f"no {task_type} preview uploaded" if typed else f"no {task_type} task"
            plan(entity_id, entity_id, preview, task_type_id, missing)
            continue
        preview_id = client.get(f"data/entities/{entity_id}").get("preview_file_id")
        preview = client.get(f"data/preview-files/{preview_id}") if preview_id else None
        if preview and is_broken(preview):
            plan(
                entity_id,
                entity_id,
                None,
                None,
                "current preview is broken in Kitsu; pass task_type to pick a revision",
            )
            continue
        preview_task = _task(preview["task_id"])["task_type_id"] if preview and preview.get("task_id") else None
        plan(entity_id, entity_id, preview, preview_task, "no preview uploaded")

    write_plan = Plan("add_to_playlist", would=f"Add {len(planned)} to playlist '{playlist['name']}'")
    for entry in planned:
        payload = {"entity_id": entry.entity_id, "preview_file_id": entry.preview_file_id}
        write_plan.request("POST", f"actions/playlists/{playlist_id}/add-entity", payload)
    write_plan.before = {"entities": len(playlist.get("shots") or [])}
    write_plan.after = {"entities": len(playlist.get("shots") or []) + len(planned)}
    write_plan.warnings = [f"Skipped {s.entity or s.ref}: {s.reason}" for s in skipped]
    if dry_run:
        return write_plan.preview()
    try:
        write_plan.send()
    except Exception as error:
        sent, cause = (error.sent, error.cause) if isinstance(error, PartialSendError) else (0, error)
        added = ", ".join(e.entity or e.entity_id for e in planned[:sent]) or "nothing"
        raise ToolError(
            f"Added {added} before failing on {planned[sent].entity}: {str(cause).rstrip('.')}. "
            "Calling add_to_playlist again with the same IDs skips what is already in."
        ) from cause

    message = f"Added {len(planned)} to '{playlist['name']}'" + (f", skipped {len(skipped)}." if skipped else ".")
    try:
        detail = playlist_detail(client.get(f"data/playlists/{playlist_id}"))
    except Exception as error:  # noqa: BLE001 - the entries are in: do not make the call look failed
        return PlaylistWriteResult(
            ok=True,
            message=f"{message} (Could not reload the playlist: {error})",
            added=planned,
            skipped=skipped,
            playlist=None,
        )
    return PlaylistWriteResult(ok=True, message=message, added=planned, skipped=skipped, playlist=detail)
