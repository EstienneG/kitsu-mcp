"""Create review playlists and fill them."""

from typing import Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import check_names, get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, PlaylistEntry, PlaylistWriteResult, SkippedEntry
from kitsu_mcp.kitsu.plans import PartialSendError, Plan
from kitsu_mcp.kitsu.validation import object_id
from kitsu_mcp.kitsu.video import is_broken
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.review.playlists import playlist_detail, project_playlists
from kitsu_mcp.tools.write.common import (
    ADDITIVE,
    ADDITIVE_IDEMPOTENT,
    WRITE,
    fetch_task_full,
)

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

    tasks = [fetch_task_full(t) for t in task_ids]
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
        preview_task = (
            fetch_task_full(preview["task_id"])["task_type_id"] if preview and preview.get("task_id") else None
        )
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
