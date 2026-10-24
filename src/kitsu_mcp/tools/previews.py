import re
from pathlib import Path
from typing import Literal

from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from kitsu_mcp import video
from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import (
    DownloadResult,
    FailedPreview,
    Playlist,
    PlaylistDetail,
    PlaylistItem,
    PreviewFile,
    SavedPreview,
)

Size = Literal["thumbnail", "preview"]

VIDEO_HINT = (
    "This preview is a video; the image is its poster frame. To look inside it use get_video_contact_sheet "
    "(overview), get_video_frames (specific frames), get_video_info, compare_revisions or review_video."
)


def _preview_bytes(preview_file_id: str, size: Size) -> bytes:
    """PNG of a preview file. Movies have PNG thumbnails/posters too."""
    kind = "previews" if size == "preview" else "thumbnails"
    return get_client().get_bytes(f"pictures/{kind}/preview-files/{preview_file_id}.png")


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "unnamed"


def _preview_file(p: dict) -> PreviewFile:
    return PreviewFile(
        id=p["id"],
        revision=p.get("revision"),
        position=p.get("position"),
        extension=p.get("extension"),
        is_movie=p.get("is_movie"),
        original_name=p.get("original_name"),
        status=p.get("status"),
        validation_status=p.get("validation_status"),
        width=p.get("width"),
        height=p.get("height"),
        created_at=p.get("created_at"),
        is_video=video.is_video(p),
        duration=p.get("duration") if video.is_video(p) else None,
        note=_note(p),
    )


def _note(p: dict) -> str | None:
    if video.is_broken(p):
        return "Broken: Kitsu could not process this upload, so there is no image or movie to show."
    return _video_note() if video.is_video(p) else None


def _video_note() -> str:
    note = "Video: see inside it with get_video_contact_sheet, get_video_frames or review_video."
    return note if video.available() else f"{note} {video.INSTALL_HINT}"


def _with_video_hint(image: Image, preview_file_id: str) -> Image | list[Image | str]:
    """Pair a poster image with a pointer to the video tools when the preview is a movie."""
    try:
        is_movie = video.is_video(get_client().get(f"data/preview-files/{preview_file_id}"))
    except ToolError:
        return image  # the image is what was asked for; the hint is a bonus
    return [image, VIDEO_HINT] if is_movie else image


@mcp.tool(annotations=READ_ONLY, tags={"previews"})
def get_preview(entity_id: str, size: Size = "thumbnail") -> Image | list[Image | str] | str:
    """Show the current preview image of an asset or shot.

    size: "thumbnail" (small, cheap) or "preview" (full resolution, large). For a video this is its
    poster frame, and the result says which video tools show more.
    """
    preview_file_id = get_client().get(f"data/entities/{entity_id}").get("preview_file_id")
    if not preview_file_id:
        return "This entity has no preview."
    return _with_video_hint(Image(data=_preview_bytes(preview_file_id, size), format="png"), preview_file_id)


@mcp.tool(annotations=READ_ONLY, tags={"previews"})
def get_preview_file(
    preview_file_id: str, show: bool = False, size: Size = "thumbnail"
) -> PreviewFile | Image | list[Image | str]:
    """Metadata of a preview file (revision, format, validation), or its image with show=True.

    Preview file IDs appear in comments (get_task) and playlists. is_video tells whether it is a
    movie; for movies show=True gives the poster frame, and the video tools show the rest.
    """
    record = get_client().get(f"data/preview-files/{preview_file_id}")
    if not show:
        return _preview_file(record)
    if video.is_broken(record):
        raise ToolError(f"Preview file {preview_file_id} is marked broken in Kitsu (its processing failed)")
    image = Image(data=_preview_bytes(preview_file_id, size), format="png")
    return [image, VIDEO_HINT] if video.is_video(record) else image


@mcp.tool(annotations=READ_ONLY, tags={"previews", "tasks"})
def list_task_previews(task_id: str) -> list[PreviewFile]:
    """All preview files uploaded on a task, newest revision first. A revision can hold several files;
    `position` 1 is its main one."""
    raw = get_client().get(f"data/tasks/{task_id}/previews")
    raw.sort(key=lambda p: (-(p.get("revision") or 0), p.get("position") or 1, p.get("created_at") or ""))
    return [_preview_file(p) for p in raw]


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}, tags={"previews"})
def download_previews(
    project: str,
    dest_dir: str,
    entity_kind: Literal["assets", "shots", "both"] = "both",
    size: Size = "preview",
    overwrite: bool = False,
) -> DownloadResult:
    """Save the preview image of every asset and/or shot of a project to a local folder.

    Writes local files only; Kitsu is not modified. Files are named <entity name>_<entity id>.png.
    Existing files are left alone (counted as skipped) unless overwrite=True. Canceled entities are skipped.
    """
    client = get_client()
    project_id = get_lookups().project(project)["id"]
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    entities = []
    if entity_kind in ("assets", "both"):
        entities += [("asset", e) for e in client.get("data/assets", params={"project_id": project_id})]
    if entity_kind in ("shots", "both"):
        entities += [("shot", e) for e in client.get("data/shots", params={"project_id": project_id})]

    saved, failed, skipped = [], [], 0
    for kind, entity in entities:
        preview_file_id = entity.get("preview_file_id")
        if not preview_file_id or entity.get("canceled"):
            skipped += 1
            continue
        path = dest / f"{_safe_filename(entity['name'])}_{_safe_filename(entity['id'])}.png"
        if path.exists() and not overwrite:
            skipped += 1
            continue
        try:
            path.write_bytes(_preview_bytes(preview_file_id, size))
        except Exception as error:
            failed.append(FailedPreview(name=entity["name"], error=str(error)))
            continue
        saved.append(SavedPreview(kind=kind, id=entity["id"], name=entity["name"], path=str(path)))
    return DownloadResult(saved=saved, skipped=skipped, failed=failed)


def _playlist(p: dict) -> Playlist:
    return Playlist(
        id=p["id"],
        name=p["name"],
        for_entity=p.get("for_entity"),
        for_client=p.get("for_client"),
        task_type=get_lookups().name("task_types", p.get("task_type_id")),
        updated_at=p.get("updated_at"),
    )


_MAX_PLAYLIST_PAGES = 50


@mcp.tool(annotations=READ_ONLY, tags={"previews", "playlists"})
def list_playlists(project: str) -> list[Playlist]:
    """List a project's review playlists, most recently updated first."""
    project_id = get_lookups().project(project)["id"]
    raw_playlists: dict[str, dict] = {}
    # The route is paginated (20 per page) and signals the end with an empty page.
    for page in range(1, _MAX_PLAYLIST_PAGES + 1):
        batch = get_client().get(f"data/projects/{project_id}/playlists", params={"page": page})
        new = {p["id"]: p for p in batch if p["id"] not in raw_playlists}
        if not new:
            break
        raw_playlists.update(new)
    playlists = [_playlist(p) for p in raw_playlists.values()]
    return sorted(playlists, key=lambda p: p.updated_at or "", reverse=True)


@mcp.tool(annotations=READ_ONLY, tags={"previews", "playlists"})
def get_playlist(playlist_id: str) -> PlaylistDetail:
    """A playlist with its entities and the preview file shown for each."""
    client = get_client()
    raw = client.get(f"data/playlists/{playlist_id}")
    items = raw.get("shots") or []
    names: dict[str, str] = {}
    if items:
        kind = "shots" if raw.get("for_entity") == "shot" else "assets"
        names = {e["id"]: e["name"] for e in client.get(f"data/{kind}", params={"project_id": raw["project_id"]})}
    return PlaylistDetail(
        **_playlist(raw).model_dump(),
        items=[
            PlaylistItem(
                entity_id=i["entity_id"], entity=names.get(i["entity_id"]), preview_file_id=i.get("preview_file_id")
            )
            for i in items
        ],
    )
