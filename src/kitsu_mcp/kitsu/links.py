"""Links to the Kitsu web app, so users open movies and pages in their browser instead of through the server.

Paths follow Kitsu's own router (cgwire/kitsu src/router/routes.js and src/lib/path.js). In a TV show, pages
of things that belong to an episode sit under it. Kitsu files an asset outside any episode under its "main"
pseudo-episode and a playlist for every episode under "all"; shots and tasks without an episode use the plain
production routes, as Kitsu's getTaskPath does.
"""

from kitsu_mcp.config import without_userinfo
from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups


def _api() -> str:
    """The Zou API URL without any login embedded in KITSU_HOST, which must never reach callers."""
    return without_userinfo(get_client().settings.host).rstrip("/")


def _base() -> str:
    return _api().removesuffix("/api")


def _is_tv_show(project_id: str) -> bool:
    project = get_lookups().index("projects").get(project_id) or {}
    return project.get("production_type") == "tvshow"


def _production(project_id: str, episode_id: str | None, default_episode: str | None = None) -> str:
    path = f"{_base()}/productions/{project_id}"
    episode = episode_id or default_episode
    if episode and _is_tv_show(project_id):
        path += f"/episodes/{episode}"
    return path


def entity_url(project_id: str | None, kind: str, entity_id: str, episode_id: str | None = None) -> str | None:
    """Page of an asset or shot. kind: "asset" or "shot"."""
    if not project_id:
        return None
    return f"{_production(project_id, episode_id, 'main' if kind == 'asset' else None)}/{kind}s/{entity_id}"


def task_url(
    project_id: str | None,
    task_id: str,
    for_entity: str | None,
    episode_id: str | None = None,
    preview_file_id: str | None = None,
) -> str | None:
    """Page of a task (its comments and previews); with a preview file, opens that preview in the player.

    episode_id: the task's episode; for a task on an Episode entity, that episode itself (its entity_id).
    """
    if not project_id:
        return None
    kind = (for_entity or "Asset").lower()
    if kind == "episode":
        if not episode_id:
            return None
        url = f"{_base()}/productions/{project_id}/episodes/{episode_id}/tasks/{task_id}"
    else:
        kind = kind if kind in ("asset", "shot", "edit", "sequence") else "asset"
        url = f"{_production(project_id, episode_id)}/{kind}s/tasks/{task_id}"
    return f"{url}/previews/{preview_file_id}" if preview_file_id else url


def download_url(preview: dict) -> str:
    """Direct download of a preview file's original upload, under its real file name. The link needs a Kitsu
    login: a browser signed in to Kitsu opens it; the server never fetches or forwards the file itself."""
    from kitsu_mcp.kitsu import video  # video imports this module's dependencies; keep the import local

    folder = "movies" if video.is_video(preview) else "pictures"
    return f"{_api()}/{folder}/originals/preview-files/{preview['id']}/download"


def playlist_url(project_id: str | None, playlist_id: str, episode_id: str | None = None) -> str | None:
    if not project_id:
        return None
    return f"{_production(project_id, episode_id, 'all')}/playlists/{playlist_id}"
