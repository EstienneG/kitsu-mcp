from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import task_summary
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import CastAsset, CastIn, Named, Sequence, ShotDetail, ShotList, ShotSummary
from kitsu_mcp.tools.assets import matches_status_filters


def _frames(value) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _text(value) -> str | None:
    """Zou sends "" or "None" for missing episode names."""
    return value if value and value != "None" else None


@mcp.tool(annotations=READ_ONLY, tags={"shots"})
def list_episodes(project: str) -> list[Named]:
    """List a project's episodes (TV shows only; empty for shorts and features)."""
    project_id = get_lookups().project(project)["id"]
    return [Named(id=e["id"], name=e["name"]) for e in get_client().get(f"data/projects/{project_id}/episodes")]


@mcp.tool(annotations=READ_ONLY, tags={"shots"})
def list_sequences(project: str, episode: str | None = None) -> list[Sequence]:
    """List a project's sequences, optionally only those of one episode (name or ID)."""
    client = get_client()
    project_id = get_lookups().project(project)["id"]
    episodes = {e["id"]: e["name"] for e in client.get(f"data/projects/{project_id}/episodes")}
    wanted = episode.lower() if episode else None
    sequences = [
        Sequence(id=s["id"], name=s["name"], episode=episodes.get(s.get("parent_id")), description=s.get("description"))
        for s in client.get(f"data/projects/{project_id}/sequences")
        if not s.get("canceled")
        and (wanted is None or wanted in {s.get("parent_id"), (episodes.get(s.get("parent_id")) or "").lower()})
    ]
    return sorted(sequences, key=lambda s: (s.episode or "", s.name))


@mcp.tool(annotations=READ_ONLY, tags={"shots"})
def list_shots(
    project: str,
    sequence: str | None = None,
    episode: str | None = None,
    task_status_filters: dict[str, list[str]] | None = None,
    name_contains: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> ShotList:
    """List a project's shots with frame ranges and tasks, optionally filtered.

    sequence / episode: names (case-insensitive) or IDs.
    task_status_filters: task type name -> allowed status short names; all must match,
    e.g. {"Animation": ["wip"], "Compositing": ["todo"]}.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    results = []
    for shot in get_client().get("data/shots/with-tasks", params={"project_id": project_id}):
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
                frame_in=_frames(shot.get("frame_in")),
                frame_out=_frames(shot.get("frame_out")),
                nb_frames=_frames(shot.get("nb_frames")),
                tasks=tasks,
            )
        )
    results.sort(key=lambda s: (s.episode or "", s.sequence or "", s.name))
    return ShotList(total=len(results), shots=results[offset : offset + limit])


@mcp.tool(annotations=READ_ONLY, tags={"shots"})
def get_shot(shot_id: str) -> ShotDetail:
    """Get a shot's details (frame range, fps, custom data) and tasks."""
    lookups = get_lookups()
    client = get_client()
    shot = client.get(f"data/shots/{shot_id}")
    tasks = client.get(f"data/shots/{shot_id}/tasks")
    return ShotDetail(
        id=shot["id"],
        name=shot["name"],
        sequence=_text(shot.get("sequence_name")),
        episode=_text(shot.get("episode_name")),
        frame_in=_frames(shot.get("frame_in")),
        frame_out=_frames(shot.get("frame_out")),
        nb_frames=_frames(shot.get("nb_frames")),
        project_id=shot.get("project_id"),
        description=shot.get("description"),
        fps=shot.get("fps"),
        data=shot.get("data"),
        tasks=[task_summary(t, lookups) for t in tasks],
    )


@mcp.tool(annotations=READ_ONLY, tags={"shots", "assets", "casting"})
def get_shot_casting(shot_id: str) -> list[CastAsset]:
    """List the assets cast in a shot (the breakdown)."""
    client = get_client()
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


@mcp.tool(annotations=READ_ONLY, tags={"shots", "assets", "casting"})
def get_asset_cast_in(asset_id: str) -> list[CastIn]:
    """List the shots an asset is cast in."""
    return [
        CastIn(
            shot_id=c["shot_id"],
            shot=c.get("shot_name"),
            sequence=c.get("sequence_name"),
            episode=_text(c.get("episode_name")),
            occurrences=c.get("nb_occurences"),
        )
        for c in get_client().get(f"data/assets/{asset_id}/cast-in")
    ]
