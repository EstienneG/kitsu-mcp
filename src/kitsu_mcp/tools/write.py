"""Tools that modify Kitsu. Registered disabled; `main()` enables them when KITSU_ALLOW_WRITE=true."""

from datetime import date
from typing import Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.app import tool
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import task_detail
from kitsu_mcp.lookups import check_names, get_lookups
from kitsu_mcp.models import PlaylistEntry, PlaylistWriteResult, SkippedEntry, WriteResult
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


@tool(annotations=ADDITIVE, tags=WRITE)
def add_comment(task_id: str, text: str, status: str | None = None) -> WriteResult:
    """Post a comment on a task as the logged-in user, optionally changing its status (short name)."""
    if not text.strip():
        raise ToolError("Comment text is empty; use set_task_status to change the status without a comment")
    task, status_name = _comment(task_id, text, status)
    changed = status_name != task["task_status"]["short_name"]
    return _result(f"Comment posted{f'; status set to {status_name}' if changed else ''}.", task_id)


@tool(annotations={**ADDITIVE, "destructiveHint": True}, tags=WRITE)
def set_task_status(task_id: str, status: str, comment: str = "") -> WriteResult:
    """Change a task's status (short name, e.g. wip, wfa, done), with an optional comment.

    Kitsu records every status change as a comment, so each call adds one to the task.
    """
    task, status_name = _comment(task_id, comment, status)
    previous = task["task_status"]["short_name"]
    if previous == status_name:
        return _result(f"Status was already {status_name}; comment posted.", task_id)
    return _result(f"Status changed from {previous} to {status_name}.", task_id)


@tool(annotations=ADDITIVE_IDEMPOTENT, tags=WRITE)
def assign_task(task_id: str, person: str) -> WriteResult:
    """Add a person (name, email or ID) to a task's assignees."""
    record = get_lookups().person(person)
    get_client().put(f"actions/persons/{record['id']}/assign", {"task_ids": [task_id]})
    return _result(f"Assigned {record.get('full_name')}.", task_id)


@tool(annotations=OVERWRITE, tags=WRITE)
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


@tool(annotations=ADDITIVE, tags=WRITE)
def log_time(task_id: str, minutes: int, day: str | None = None, person: str | None = None) -> WriteResult:
    """Add time spent on a task (minutes) for a day (YYYY-MM-DD, default today), as the logged-in user by default."""
    if not 0 < minutes <= 24 * 60:
        raise ToolError("minutes must be between 1 and 1440")
    when = iso_date(day, "day") if day else date.today().isoformat()
    person_id = get_lookups().person(person)["id"] if person else get_client().user_id()
    get_client().post(f"actions/tasks/{task_id}/time-spents/{when}/persons/{person_id}/add", {"duration": minutes})
    return _result(f"Logged {minutes} min on {when}.", task_id)


MAX_PLAYLIST_ADDS = 50


@tool(annotations=ADDITIVE, tags=WRITE)
def create_playlist(
    project: str,
    name: str,
    for_entity: Literal["shot", "asset"],
    episode: str | None = None,
    task_type: str | None = None,
    for_client: bool = False,
) -> PlaylistWriteResult:
    """Create an empty review playlist of shots or assets in a project; fill it with add_to_playlist.

    project: name or ID. name: must not already be used by a playlist of the project (the error gives
    the existing one's ID). episode: name or ID, required for shot playlists of TV shows, not allowed
    in other productions. task_type: name, shown as the playlist's task type in Kitsu. for_client: share
    it with client accounts. Returns the new playlist (`playlist.id` is what add_to_playlist takes).
    """
    lookups = get_lookups()
    record = lookups.project(project)
    name = name.strip()
    if not name:
        raise ToolError("Playlist name is empty")
    for existing in project_playlists(record["id"]):
        if existing["name"].strip().lower() == name.lower():
            raise ToolError(
                f"{record['name']} already has a playlist named '{existing['name']}' (ID {existing['id']}); "
                "pick another name, or add to it with add_to_playlist"
            )
    data: dict = {"name": name, "project_id": record["id"], "for_entity": for_entity, "for_client": for_client}
    is_show = record.get("production_type") == "tvshow"
    if episode is not None:
        if not is_show:
            raise ToolError(f"{record['name']} is not a TV show: it has no episodes, leave episode out")
        episodes = get_client().get(f"data/projects/{record['id']}/episodes")
        match = [e for e in episodes if episode in (e["id"], e["name"]) or e["name"].lower() == episode.lower()]
        if not match:
            check_names("episode", [episode], {e["name"] for e in episodes})
        data["episode_id"] = match[0]["id"]
    elif is_show and for_entity == "shot":
        raise ToolError(f"{record['name']} is a TV show: pass the episode of the shots (list_episodes)")
    if task_type is not None:
        data["task_type_id"] = lookups.task_type(task_type)["id"]
    raw = get_client().post("data/playlists/", data)
    message = f"Created playlist '{name}' in {record['name']}."
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
    playlist_id: str, task_ids: list[str] | None = None, entity_ids: list[str] | None = None
) -> PlaylistWriteResult:
    """Add shots or assets to a playlist (at most 50 per call), each with the preview to review.

    task_ids: tasks (e.g. from search_tasks); each adds its shot or asset with that task's latest
    revision (main file, broken uploads skipped). entity_ids: shots or assets; each is added with the
    preview Kitsu currently shows for it. Everything must belong to the playlist's project and match
    what it holds (shots or assets), else nothing is added. Entities already in the playlist, or without
    a preview, are skipped and listed in `skipped`; so a repeated call adds nothing twice.
    `added` gives each entity with the task type and revision it shows.
    """
    task_ids = [object_id(t, "task", "search_tasks") for t in task_ids or []]
    entity_ids = [object_id(e, "entity", "list_shots or list_assets") for e in entity_ids or []]
    if not task_ids and not entity_ids:
        raise ToolError("Nothing to add: pass task_ids and/or entity_ids")
    if len(task_ids) + len(entity_ids) > MAX_PLAYLIST_ADDS:
        raise ToolError(f"At most {MAX_PLAYLIST_ADDS} tasks and entities per call; split the list")
    client = get_client()
    lookups = get_lookups()
    playlist_id = object_id(playlist_id, "playlist", "list_playlists")
    playlist = client.get(f"data/playlists/{playlist_id}")
    kind = playlist.get("for_entity")
    if kind not in ("shot", "asset"):
        raise ToolError(f"Playlist '{playlist['name']}' holds {kind}s; only shot and asset playlists are supported")
    names = {e["id"]: e["name"] for e in client.get(f"data/{kind}s", params={"project_id": playlist["project_id"]})}
    project_name = lookups.name("projects", playlist["project_id"]) or playlist["project_id"]

    def check_entity(entity_id: str, ref: str) -> None:
        if entity_id not in names:
            raise ToolError(
                f"{ref} is not a {kind} of {project_name}, so it cannot go in playlist '{playlist['name']}'; "
                "nothing was added"
            )

    # Resolve and check everything before the first write, so a bad ID never leaves a half-filled playlist.
    present = {e["entity_id"] for e in playlist.get("shots") or []}
    planned: list[PlaylistEntry] = []
    skipped: list[SkippedEntry] = []

    def plan(ref: str, entity_id: str, preview: dict | None, task_type_id: str | None) -> None:
        entity = names[entity_id]
        if entity_id in present:
            skipped.append(SkippedEntry(ref=ref, entity=entity, reason="already in the playlist"))
        elif preview is None:
            skipped.append(SkippedEntry(ref=ref, entity=entity, reason="no preview uploaded"))
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
        plan(task["id"], task["entity_id"], _latest_preview(task["id"]), task["task_type_id"])
    for entity_id in entity_ids:
        preview_id = client.get(f"data/entities/{entity_id}").get("preview_file_id")
        preview = client.get(f"data/preview-files/{preview_id}") if preview_id else None
        task_type_id = _task(preview["task_id"])["task_type_id"] if preview and preview.get("task_id") else None
        plan(entity_id, entity_id, preview, task_type_id)

    for done, entry in enumerate(planned):
        try:
            client.post(
                f"actions/playlists/{playlist_id}/add-entity",
                {"entity_id": entry.entity_id, "preview_file_id": entry.preview_file_id},
            )
        except ToolError as error:
            added = ", ".join(e.entity or e.entity_id for e in planned[:done]) or "nothing"
            raise ToolError(
                f"Added {added} before failing on {entry.entity}: {error}. "
                "Calling add_to_playlist again with the same IDs skips what is already in."
            ) from error

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
