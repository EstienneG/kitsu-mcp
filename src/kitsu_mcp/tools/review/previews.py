import re
from pathlib import Path
from typing import Literal

from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from kitsu_mcp.kitsu import links, video
from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.formatters import task_link
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import (
    DownloadResult,
    FailedPreview,
    PreviewFile,
    RecentPreview,
    RecentPreviews,
    SavedPreview,
)
from kitsu_mcp.kitsu.validation import Limit, iso_date, object_id
from kitsu_mcp.server.app import READ_ONLY, tool

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


def _preview_file(p: dict, task: dict | None = None) -> PreviewFile:
    """`task`: the preview's `data/tasks/<id>/full` record, to link to the preview in Kitsu's player."""
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
        url=task_link(task, p["id"]) if task else None,
        download_url=links.download_url(p),
    )


def _task_full(task_id: str | None) -> dict | None:
    return get_client().get(f"data/tasks/{task_id}/full") if task_id else None


def _note(p: dict) -> str | None:
    if video.is_broken(p):
        return "Broken: Kitsu could not process this upload, so there is no image or movie to show."
    return _video_note() if video.is_video(p) else None


def _video_note() -> str:
    note = "Video: see inside it with get_video_contact_sheet, get_video_frames or review_video."
    return note if video.available() else f"{note} {video.INSTALL_HINT}"


@tool(annotations=READ_ONLY, tags={"review"})
def get_preview(
    entity_id: str | None = None,
    preview_file_id: str | None = None,
    show: bool = True,
    size: Size = "thumbnail",
) -> PreviewFile | Image | list[Image | str] | str:
    """A preview: an asset or shot's current one (entity_id), or a given upload (preview_file_id).

    show=True (default) returns the image; show=False its metadata (revision, format, status,
    validation, is_video). size: "thumbnail" (small, cheap) or "preview" (full resolution, large).
    For a video the image is its poster frame, and the result says which video tools show more.
    Preview file IDs appear in comments (get_task), a task's previews (get_task with include_previews) and playlists.
    """
    if bool(entity_id) == bool(preview_file_id):
        raise ToolError("Pass exactly one of entity_id or preview_file_id")
    client = get_client()
    if entity_id:
        entity_id = object_id(entity_id, "asset or shot", "list_assets or list_shots")
        preview_file_id = client.get(f"data/entities/{entity_id}").get("preview_file_id")
        if not preview_file_id:
            return "This entity has no preview."
    preview_file_id = object_id(preview_file_id or "", "preview file", "get_task(include_previews=True)")
    try:
        record = client.get(f"data/preview-files/{preview_file_id}")
    except ToolError:
        if not show or not entity_id:
            raise
        # The entity's image is what was asked for; its metadata (video hint, broken flag) is a bonus.
        return Image(data=_preview_bytes(preview_file_id, size), format="png")
    if not show:
        return _preview_file(record, _task_full(record.get("task_id")))
    if video.is_broken(record):
        raise ToolError(f"Preview file {preview_file_id} is marked broken in Kitsu (its processing failed)")
    image = Image(data=_preview_bytes(preview_file_id, size), format="png")
    return [image, VIDEO_HINT] if video.is_video(record) else image


def task_previews(task_id: str, task: dict | None = None) -> list[PreviewFile]:
    """All preview files uploaded on a task, newest revision first (get_task(include_previews=True))."""
    raw = get_client().get(f"data/tasks/{task_id}/previews")
    raw.sort(key=lambda p: (-(p.get("revision") or 0), p.get("position") or 1, p.get("created_at") or ""))
    task = (task or _task_full(task_id)) if raw else None
    return [_preview_file(p, task) for p in raw]


@tool(annotations=READ_ONLY, tags={"review"})
def recent_previews(
    project: str,
    task_type: str | None = None,
    since: str | None = None,
    videos_only: bool = False,
    entity_name_contains: str | None = None,
    limit: Limit = 20,
) -> RecentPreviews:
    """Latest uploads (previews) on a project, newest first, from its activity feed.

    Answers "what was uploaded today?" or "show me the latest animation of SH020": filter by task type
    (name or short name), since (YYYY-MM-DD), videos_only, or entity_name_contains, then pass a
    preview_file_id to get_preview (show=False gives its Kitsu page and download links), get_video_contact_sheet
    or review_video.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    params: dict = {"only_preview": "true"}
    if task_type:
        params["task_type_id"] = lookups.task_type(task_type)["id"]
    if since:
        params["after"] = iso_date(since, "since")
    wanted = (entity_name_contains or "").lower()
    found: list[RecentPreview] = []
    total = 0
    # Name and video filters apply on our side, so read a few pages of the feed to fill `limit`.
    for page in range(1, _MAX_FEED_PAGES + 1):
        feed = get_client().get(f"data/projects/{project_id}/news", params={**params, "page": page, "limit": 100})
        total = feed.get("total") or total
        for item in feed.get("data") or []:
            if not item.get("preview_file_id"):
                continue
            is_movie = video.is_video({"extension": item.get("preview_file_extension")})
            if (videos_only and not is_movie) or (
                wanted and wanted not in (item.get("full_entity_name") or "").lower()
            ):
                continue
            found.append(
                RecentPreview(
                    date=item.get("created_at"),
                    entity=item.get("full_entity_name"),
                    entity_id=item.get("task_entity_id"),
                    task_id=item.get("task_id"),
                    task_type=lookups.name("task_types", item.get("task_type_id")),
                    status=lookups.name("task_statuses", item.get("task_status_id"), "short_name"),
                    author=lookups.person_name(item.get("author_id")),
                    preview_file_id=item["preview_file_id"],
                    revision=item.get("preview_file_revision"),
                    extension=item.get("preview_file_extension"),
                    is_video=is_movie,
                )
            )
            if len(found) == limit:
                return RecentPreviews(total=total, previews=found)
        if page >= (feed.get("nb_pages") or 1):
            break
    return RecentPreviews(total=total, previews=found)


_MAX_FEED_PAGES = 5


@tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}, tags={"review", "local"})
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
    Only on a local server; preview metadata (get_preview with show=False) carries a `download_url` instead.
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

    saved, failed = [], []
    skips = {"no_preview": 0, "canceled": 0, "already_downloaded": 0}
    for kind, entity in entities:
        preview_file_id = entity.get("preview_file_id")
        if entity.get("canceled"):
            skips["canceled"] += 1
            continue
        if not preview_file_id:
            skips["no_preview"] += 1
            continue
        path = dest / f"{_safe_filename(entity['name'])}_{_safe_filename(entity['id'])}.png"
        if path.exists() and not overwrite:
            skips["already_downloaded"] += 1
            continue
        try:
            path.write_bytes(_preview_bytes(preview_file_id, size))
        except Exception as error:
            failed.append(FailedPreview(name=entity["name"], error=str(error)))
            continue
        saved.append(SavedPreview(kind=kind, id=entity["id"], name=entity["name"], path=str(path)))
    return DownloadResult(saved=saved, skipped=sum(skips.values()), **skips, failed=failed)
