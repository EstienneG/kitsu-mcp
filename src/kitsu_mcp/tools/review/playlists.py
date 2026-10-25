"""Review playlists: list them and read one (creating and filling them are write tools)."""

from kitsu_mcp.kitsu import links
from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import Playlist, PlaylistDetail, PlaylistItem, PlaylistList
from kitsu_mcp.kitsu.validation import Limit, Offset, object_id
from kitsu_mcp.server.app import READ_ONLY, tool


def _playlist(p: dict) -> Playlist:
    return Playlist(
        id=p["id"],
        name=p["name"],
        for_entity=p.get("for_entity"),
        for_client=p.get("for_client"),
        task_type=get_lookups().name("task_types", p.get("task_type_id")),
        updated_at=p.get("updated_at"),
        url=links.playlist_url(p.get("project_id"), p["id"], p.get("episode_id")),
    )


_MAX_PLAYLIST_PAGES = 50


def project_playlists(project_id: str) -> list[dict]:
    """Every playlist of a project, as Zou returns them."""
    playlists: dict[str, dict] = {}
    # The route is paginated (20 per page) and signals the end with an empty page.
    for page in range(1, _MAX_PLAYLIST_PAGES + 1):
        batch = get_client().get(f"data/projects/{project_id}/playlists", params={"page": page})
        new = {p["id"]: p for p in batch if p["id"] not in playlists}
        if not new:
            break
        playlists.update(new)
    return list(playlists.values())


@tool(annotations=READ_ONLY, tags={"review"})
def list_playlists(project: str, limit: Limit = 50, offset: Offset = 0) -> PlaylistList:
    """List a project's review playlists, most recently updated first. `total` counts them all."""
    project_id = get_lookups().project(project)["id"]
    raw_playlists = project_playlists(project_id)
    playlists = sorted((_playlist(p) for p in raw_playlists), key=lambda p: p.updated_at or "", reverse=True)
    return PlaylistList(total=len(playlists), playlists=playlists[offset : offset + limit])


@tool(annotations=READ_ONLY, tags={"review"})
def get_playlist(playlist_id: str) -> PlaylistDetail:
    """A playlist with its entities and the preview file shown for each."""
    playlist_id = object_id(playlist_id, "playlist", "list_playlists")
    return playlist_detail(get_client().get(f"data/playlists/{playlist_id}"))


def playlist_detail(raw: dict) -> PlaylistDetail:
    """A Zou playlist with its entries named. Kitsu keeps entries under `shots` whatever the playlist holds."""
    items = raw.get("shots") or []
    names: dict[str, str] = {}
    if items:
        kind = "shots" if raw.get("for_entity") == "shot" else "assets"
        names = {e["id"]: e["name"] for e in get_client().get(f"data/{kind}", params={"project_id": raw["project_id"]})}
    return PlaylistDetail(
        **_playlist(raw).model_dump(),
        items=[
            PlaylistItem(
                entity_id=i["entity_id"], entity=names.get(i["entity_id"]), preview_file_id=i.get("preview_file_id")
            )
            for i in items
        ],
    )
