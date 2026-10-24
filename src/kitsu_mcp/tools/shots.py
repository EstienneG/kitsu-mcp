from fastmcp.exceptions import ToolError

from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import task_summary
from kitsu_mcp.lookups import check_names, get_lookups
from kitsu_mcp.models import CastAsset, CastIn, Named, Sequence, ShotDetail, ShotList, ShotSummary
from kitsu_mcp.tools.assets import check_status_filters, matches_status_filters, statuses
from kitsu_mcp.validation import Detail, Limit, Offset, object_id


def _frames(shot: dict, field: str) -> int | None:
    """Frame fields live at the top level on recent Zou, in `data` on shots created through gazu."""
    value = shot.get(field)
    if value is None:
        value = (shot.get("data") or {}).get(field)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (ValueError, OverflowError):
            return None
    return None


def _fps(value) -> float | None:
    """Zou stores fps as text ("24", "23.976")."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _text(value) -> str | None:
    """Zou sends "" or "None" for missing episode names."""
    return value if value and value != "None" else None


@tool(annotations=READ_ONLY, tags={"shots"})
def list_episodes(project: str) -> list[Named]:
    """List a project's episodes (TV shows only; empty for shorts and features)."""
    project_id = get_lookups().project(project)["id"]
    return [Named(id=e["id"], name=e["name"]) for e in get_client().get(f"data/projects/{project_id}/episodes")]


@tool(annotations=READ_ONLY, tags={"shots"})
def list_sequences(project: str, episode: str | None = None) -> list[Sequence]:
    """List a project's sequences, optionally only those of one episode (name or ID)."""
    client = get_client()
    project_id = get_lookups().project(project)["id"]
    episodes = {e["id"]: e["name"] for e in client.get(f"data/projects/{project_id}/episodes")}
    if episode and episode not in episodes:
        check_names("episode", [episode], set(episodes.values()))
    wanted = episode.lower() if episode else None
    sequences = [
        Sequence(id=s["id"], name=s["name"], episode=episodes.get(s.get("parent_id")), description=s.get("description"))
        for s in client.get(f"data/projects/{project_id}/sequences")
        if not s.get("canceled")
        and (wanted is None or wanted in {s.get("parent_id"), (episodes.get(s.get("parent_id")) or "").lower()})
    ]
    return sorted(sequences, key=lambda s: (s.episode or "", s.name))


@tool(annotations=READ_ONLY, tags={"shots"})
def list_shots(
    project: str,
    sequence: str | None = None,
    episode: str | None = None,
    task_status_filters: dict[str, list[str]] | None = None,
    name_contains: str | None = None,
    detail: Detail = "compact",
    limit: Limit = 100,
    offset: Offset = 0,
) -> ShotList:
    """List a project's shots with frame ranges and tasks, optionally filtered.

    detail="compact" (default) gives each shot's tasks as {task type: status}; detail="full" returns
    full task rows (IDs, assignees, due dates, latest preview), several times larger. get_shot has the details.
    sequence / episode: names (case-insensitive) or IDs.
    task_status_filters: task type name -> allowed status short names; all must match,
    e.g. {"Animation": ["wip"], "Compositing": ["todo"]}.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    check_status_filters(task_status_filters, lookups)
    shots = get_client().get("data/shots/with-tasks", params={"project_id": project_id})
    if sequence and sequence not in {s.get("sequence_id") for s in shots}:
        check_names("sequence", [sequence], {s.get("sequence_name") or "" for s in shots})
    if episode and episode not in {s.get("episode_id") for s in shots}:
        check_names("episode", [episode], {s.get("episode_name") or "" for s in shots})
    results = []
    for shot in shots:
        if shot.get("canceled"):
            continue
        if sequence and sequence.lower() not in {(shot.get("sequence_name") or "").lower(), shot.get("sequence_id")}:
            continue
        if episode and episode.lower() not in {(shot.get("episode_name") or "").lower(), shot.get("episode_id")}:
            continue
        if name_contains and name_contains.lower() not in shot.get("name", "").lower():
            continue
        tasks = [task_summary(t, lookups) for t in shot.get("tasks") or []]
        if not matches_status_filters(tasks, task_status_filters):
            continue
        results.append(
            ShotSummary(
                id=shot["id"],
                name=shot["name"],
                sequence=_text(shot.get("sequence_name")),
                episode=_text(shot.get("episode_name")),
                frame_in=_frames(shot, "frame_in"),
                frame_out=_frames(shot, "frame_out"),
                nb_frames=_frames(shot, "nb_frames"),
                tasks=None if detail == "compact" else tasks,
                statuses=statuses(tasks) if detail == "compact" else None,
            )
        )
    results.sort(key=lambda s: (s.episode or "", s.sequence or "", s.name))
    return ShotList(total=len(results), shots=results[offset : offset + limit])


@tool(annotations=READ_ONLY, tags={"shots"})
def get_shot(shot_id: str) -> ShotDetail:
    """Get a shot's details (frame range, fps, custom data) and tasks."""
    shot_id = object_id(shot_id, "shot", "list_shots")
    lookups = get_lookups()
    client = get_client()
    shot = client.get(f"data/shots/{shot_id}")
    tasks = client.get(f"data/shots/{shot_id}/tasks")
    return ShotDetail(
        id=shot["id"],
        name=shot["name"],
        sequence=_text(shot.get("sequence_name")),
        episode=_text(shot.get("episode_name")),
        frame_in=_frames(shot, "frame_in"),
        frame_out=_frames(shot, "frame_out"),
        nb_frames=_frames(shot, "nb_frames"),
        project_id=shot.get("project_id"),
        description=shot.get("description"),
        fps=_fps(shot.get("fps")),
        data=shot.get("data"),
        tasks=[task_summary(t, lookups) for t in tasks],
    )


@tool(annotations=READ_ONLY, tags={"shots", "assets", "casting"})
def get_casting(shot_id: str | None = None, asset_id: str | None = None) -> list[CastAsset] | list[CastIn]:
    """Casting (the breakdown), either way: the assets cast in a shot (shot_id), or the shots an asset
    is cast in (asset_id)."""
    if bool(shot_id) == bool(asset_id):
        raise ToolError("Pass exactly one of shot_id or asset_id")
    client = get_client()
    if shot_id:
        shot_id = object_id(shot_id, "shot", "list_shots")
        project_id = client.get(f"data/shots/{shot_id}")["project_id"]
        return [
            CastAsset(
                asset_id=c["asset_id"],
                name=c.get("asset_name") or c.get("name"),
                asset_type=c.get("asset_type_name"),
                occurrences=c.get("nb_occurences"),
                label=c.get("label"),
            )
            for c in client.get(f"data/projects/{project_id}/entities/{shot_id}/casting")
        ]
    asset_id = object_id(asset_id or "", "asset", "list_assets")
    return [
        CastIn(
            shot_id=c["shot_id"],
            shot=c.get("shot_name"),
            sequence=c.get("sequence_name"),
            episode=_text(c.get("episode_name")),
            occurrences=c.get("nb_occurences"),
        )
        for c in client.get(f"data/assets/{asset_id}/cast-in")
    ]
