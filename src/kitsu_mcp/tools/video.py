"""Video tools: look inside movie previews. Need the optional `video` extra (PyAV + Pillow)."""

import json
import shutil
from pathlib import Path

from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from kitsu_mcp import video
from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import comment as format_comment
from kitsu_mcp.models import SavedVideo, VideoInfo
from kitsu_mcp.tools.previews import _safe_filename
from kitsu_mcp.video import ImageFormat, Probe, Quality

VIDEO = {"previews", "video"}
Moment = int | float | str


def _open(preview_file_id: str | None, entity_id: str | None, quality: Quality) -> tuple[dict, Path, Probe]:
    video.require()
    preview = video.resolve_preview(preview_file_id, entity_id)
    path = video.fetch(preview, quality)
    return preview, path, video.probe(path)


def _info(preview: dict, path: Path, probe: Probe, quality: Quality) -> VideoInfo:
    return VideoInfo(
        preview_file_id=preview["id"],
        task_id=preview.get("task_id"),
        revision=preview.get("revision"),
        original_name=preview.get("original_name"),
        extension=preview.get("extension"),
        quality=quality,
        file_bytes=path.stat().st_size,
        codec=probe.codec,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        duration=probe.duration,
        frame_count=probe.frame_count,
        kitsu_width=preview.get("width"),
        kitsu_height=preview.get("height"),
        kitsu_duration=preview.get("duration"),
        original_file_size=video.original_size(preview),
        annotated_frames=video.annotation_frames(preview, probe.fps),
    )


def _sheet(path: Path, probe: Probe, frames: list[int], fmt: ImageFormat, prefix: str = "") -> Image:
    images = video.grab(path, frames, probe)
    columns = min(4, len(frames)) if len(frames) != 9 else 3
    cells = [(images[f], video.frame_label(f, probe.fps, prefix)) for f in frames]
    return video.encode(video.grid(list(cells), columns, probe.height / probe.width), fmt)


@tool(annotations=READ_ONLY, tags=VIDEO)
def get_video_info(
    preview_file_id: str | None = None, entity_id: str | None = None, quality: Quality = "low"
) -> VideoInfo:
    """Duration, fps, frame count, resolution and codec of a movie preview, read from the file itself.

    Pass a preview_file_id, or an entity_id (shot/asset) to use its current preview. Also returns
    Kitsu's own metadata and the frames that carry drawn annotations. quality="low" probes Kitsu's
    web-playback encode (downloaded and cached), "original" the uploaded file.
    """
    preview, path, probe = _open(preview_file_id, entity_id, quality)
    return _info(preview, path, probe, quality)


@tool(annotations=READ_ONLY, tags=VIDEO)
def get_video_contact_sheet(
    preview_file_id: str | None = None,
    entity_id: str | None = None,
    n: int = 12,
    quality: Quality = "low",
    format: ImageFormat = "jpeg",
) -> Image:
    """One image: a grid of n evenly spaced frames of a movie preview, each labelled #frame and timecode.

    The cheapest way to see what happens in a shot. n: 1-16. Frames are numbered from 1 like
    Kitsu's player; timecodes are HH:MM:SS:FF. Pass a preview_file_id, or an entity_id to use its current preview.
    """
    video.check_count(n)
    _, path, probe = _open(preview_file_id, entity_id, quality)
    return _sheet(path, probe, video.even_frames(n, probe.frame_count), format)


@tool(annotations=READ_ONLY, tags=VIDEO)
def get_video_frames(
    frames: list[Moment],
    preview_file_id: str | None = None,
    entity_id: str | None = None,
    quality: Quality = "low",
    max_side: int = 960,
    format: ImageFormat = "jpeg",
) -> list[Image]:
    """Specific frames of a movie preview, one labelled image each (at most 16).

    frames: frame numbers (37, counted from 1 like Kitsu's player), timecodes ("00:00:01:12" =
    HH:MM:SS:FF), times ("1.5s", "0:02.5") or percentages of the duration ("50%"). max_side: longest
    side of each image in pixels (64-1280). Use quality="original" for full detail.
    """
    if not frames or len(frames) > video.MAX_FRAMES:  # before downloading anything
        video.parse_moments(frames, 1.0, 1)
    _, path, probe = _open(preview_file_id, entity_id, quality)
    wanted = video.parse_moments(frames, probe.fps, probe.frame_count)
    images = video.grab(path, wanted, probe)
    return [video.encode(video.single(images[f], video.frame_label(f, probe.fps), max_side), format) for f in wanted]


def _latest_two(task_id: str) -> tuple[dict, dict]:
    """The main movies of the task's two latest distinct revisions, older first."""
    latest = video.latest_revisions(task_id, 2)
    if len(latest) < 2:
        raise ToolError(
            f"Task {task_id} has movies in {len(latest)} revision(s); comparing needs two. "
            "To compare two files of the same revision, pass preview_file_a and preview_file_b."
        )
    return latest[1], latest[0]


@tool(annotations=READ_ONLY, tags=VIDEO | {"tasks"})
def compare_revisions(
    preview_file_a: str | None = None,
    preview_file_b: str | None = None,
    task_id: str | None = None,
    n: int = 6,
    frames: list[Moment] | None = None,
    quality: Quality = "low",
    format: ImageFormat = "jpeg",
) -> list[str | Image]:
    """The same moments of two movie previews side by side (A left, B right), in one image.

    Give two preview file IDs, or a task_id to compare the main movies of its two latest revisions
    (older = A). Moments are n evenly spaced points (1-8), or `frames` (frame numbers, timecodes,
    seconds or percentages, at most 8). Moments are matched by time, so revisions of different lengths
    line up by timecode; percentages are applied to each movie. A moment past the end of the shorter
    movie is shown as an empty "past end" cell.
    """
    video.require()
    if task_id and (preview_file_a or preview_file_b):
        raise ToolError("Pass either task_id or preview_file_a and preview_file_b")
    if task_id:
        raw_a, raw_b = _latest_two(task_id)
    elif preview_file_a and preview_file_b:
        raw_a, raw_b = video.resolve_preview(preview_file_a, None), video.resolve_preview(preview_file_b, None)
    else:
        raise ToolError("Pass preview_file_a and preview_file_b, or a task_id")
    limit = video.MAX_FRAMES // 2
    if frames is not None and len(frames) > limit:
        raise ToolError(f"At most {limit} moments when comparing (got {len(frames)})")
    if not 1 <= n <= limit:
        raise ToolError(f"n must be between 1 and {limit}")
    sides = []
    for raw in (raw_a, raw_b):
        path = video.fetch(raw, quality)
        sides.append((raw, path, video.probe(path)))
    (_, _, probe_a), (_, _, probe_b) = sides[0], sides[1]

    # Moments as seconds (or percentages), so they map onto both movies. None = past this movie's end.
    def moments_for(probe: Probe) -> list[int | None]:
        if frames is None:
            longest = max(probe_a.duration, probe_b.duration) or 1
            times = [(i + 0.5) * longest / n for i in range(n)]
            return [_within(video.frame_at(t, probe.fps), probe) for t in times]
        result: list[int | None] = []
        for spec in frames:
            if isinstance(spec, str) and spec.strip().endswith("%"):
                result.append(video.parse_moment(spec, probe.fps, probe.frame_count))
                continue
            # Interpret on A's timeline, then carry the time over.
            frame_a = video.parse_moment(spec, probe_a.fps, max(probe_a.frame_count, probe_b.frame_count))
            seconds = (frame_a - 1) / probe_a.fps
            result.append(_within(video.frame_at(seconds, probe.fps), probe))
        return result

    columns: list[list[tuple | None]] = []
    past_end: dict[str, int] = {}
    for side, (raw, path, probe) in zip("ab", sides, strict=True):
        wanted = moments_for(probe)
        present = [f for f in wanted if f is not None]
        images = video.grab(path, present, probe) if present else {}
        prefix = f"v{raw.get('revision')} " if raw.get("revision") is not None else ""
        columns.append([None if f is None else (images[f], video.frame_label(f, probe.fps, prefix)) for f in wanted])
        if missing := sum(f is None for f in wanted):
            past_end[side] = missing
    cells = [cell for pair in zip(*columns, strict=True) for cell in pair]
    headers = [f"{side}: rev {raw.get('revision')} ({raw['id'][:8]})" for side, raw in (("A", raw_a), ("B", raw_b))]
    aspect = max(probe_a.height / probe_a.width, probe_b.height / probe_b.width)
    sheet = video.grid(cells, 2, aspect, headers=headers)
    summary = {
        side: {
            "preview_file_id": raw["id"],
            "revision": raw.get("revision"),
            "duration": probe.duration,
            **({"moments_past_end": past_end[side]} if side in past_end else {}),
        }
        for side, (raw, _, probe) in zip("ab", sides, strict=True)
    }
    return [json.dumps(summary), video.encode(sheet, format)]


def _within(frame: int, probe: Probe) -> int | None:
    return frame if 1 <= frame <= probe.frame_count else None


@tool(annotations=READ_ONLY, tags=VIDEO | {"tasks"})
def review_video(
    task_id: str,
    preview_file_id: str | None = None,
    max_frames: int = 8,
    include_other_revisions: bool = False,
    quality: Quality = "low",
    format: ImageFormat = "jpeg",
) -> list[str | Image] | str:
    """A task's latest movie with the frames its comments point at, for reviewing feedback.

    Reads the task's comments (newest first) and finds the frames they reference: Kitsu timecode
    tags ("v3 00:00:01:12 (37)"), timecodes, "frame 37", "1.5s", and frames with drawn annotations on
    the movie. Each comment is tied to the revision that was current when it was posted
    (`about_revision`); only references about the reviewed revision are placed on its frames, unless
    include_other_revisions=True. Returns a JSON summary (each comment with its frames), then one
    labelled image per referenced frame (at most max_frames, 1-16, newest comments first). Pass
    preview_file_id to review another movie than the latest revision's main one.
    """
    video.require()
    if not 1 <= max_frames <= video.MAX_FRAMES:
        raise ToolError(f"max_frames must be between 1 and {video.MAX_FRAMES}")
    client = get_client()
    videos = video.task_videos(task_id)
    if preview_file_id:
        preview = video.resolve_preview(preview_file_id, None)
        if preview.get("task_id") not in (None, task_id):
            raise ToolError(f"Preview file {preview_file_id} belongs to task {preview['task_id']}, not {task_id}")
    else:
        latest = video.latest_revisions(task_id, 1)
        if not latest:
            raise ToolError(f"Task {task_id} has no playable movie preview")
        preview = latest[0]
    path = video.fetch(preview, quality)
    probe = video.probe(path)
    revision = preview.get("revision")

    comments, wanted = [], []
    for raw in client.get(f"data/tasks/{video.check_id(task_id, 'task ID')}/comments"):
        about = _revision_at(videos, raw)
        refs = video.find_references(raw.get("text"), probe.fps, probe.frame_count)
        frames, elsewhere = [], set()
        for ref in refs:
            ref_revision = ref.revision if ref.revision is not None else about
            if ref_revision is not None and revision is not None and ref_revision != revision:
                elsewhere.add(ref_revision)
                if ref.revision is not None or not include_other_revisions:
                    continue  # a frame of another revision's timeline
            if 1 <= ref.frame <= probe.frame_count:
                frames.append(ref.frame)
        formatted = format_comment(raw).model_dump(exclude={"preview_ids"})
        if not (formatted.get("text") or "").strip() and not frames:
            continue
        comments.append(
            {
                **formatted,
                "about_revision": about,
                "frames": [{"frame": f, "timecode": video.timecode(f, probe.fps)} for f in dict.fromkeys(frames)],
                **({"refers_to_other_revisions": sorted(elsewhere)} if elsewhere else {}),
            }
        )
        wanted += frames

    annotated = video.annotation_frames(preview, probe.fps)
    annotated = [f for f in annotated if 1 <= f <= probe.frame_count]
    ordered = list(dict.fromkeys(wanted + annotated))
    shown, omitted = ordered[:max_frames], ordered[max_frames:]
    images = video.grab(path, shown, probe) if shown else {}
    summary = {
        "task_id": task_id,
        "preview_file_id": preview["id"],
        "revision": revision,
        "duration": probe.duration,
        "fps": probe.fps,
        "frame_count": probe.frame_count,
        "annotated_frames": annotated,
        "comments": comments,
        "frames_shown": shown,
        **({"frames_omitted": omitted} if omitted else {}),
        **(
            {"note": "No comment references a frame; use get_video_contact_sheet for an overview."} if not shown else {}
        ),
    }
    if not shown:
        return json.dumps(summary, ensure_ascii=False)
    result: list[str | Image] = [json.dumps(summary, ensure_ascii=False)]
    for frame in shown:
        label = video.frame_label(frame, probe.fps, f"v{revision} " if revision is not None else "")
        if frame in annotated:
            label += "  (annotated)"
        result.append(video.encode(video.single(images[frame], label, 768), format))
    return result


def _revision_at(videos: list[dict], comment: dict) -> int | None:
    """The revision a comment is about: the one it uploaded, else the latest uploaded before it."""
    for attached in comment.get("previews") or []:
        if isinstance(attached, dict) and attached.get("revision") is not None:
            return attached["revision"]
    posted = comment.get("created_at") or ""
    earlier = [rev for v in videos if (rev := v.get("revision")) is not None and (v.get("created_at") or "") <= posted]
    return max(earlier) if earlier else None


@tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}, tags=VIDEO)
def download_video(
    dest_dir: str,
    preview_file_id: str | None = None,
    entity_id: str | None = None,
    quality: Quality = "low",
    overwrite: bool = False,
) -> SavedVideo:
    """Save a movie preview to a local folder.

    Writes local files only; Kitsu is not modified. The file is named <original name>_<preview file id>.<ext>.
    An existing file is left alone (skipped=True) unless overwrite=True. quality="low" is Kitsu's
    web-playback encode, "original" the uploaded file. Does not need the video extra.
    """
    preview = video.resolve_preview(preview_file_id, entity_id)
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(preview.get("original_name") or "movie")
    target = dest / f"{stem}_{_safe_filename(preview['id'])}.{video.file_extension(preview, quality)}"
    if target.exists() and not overwrite:
        return SavedVideo(
            preview_file_id=preview["id"], path=str(target), quality=quality, bytes=target.stat().st_size, skipped=True
        )
    source = video.fetch(preview, quality)
    shutil.copyfile(source, target)
    return SavedVideo(preview_file_id=preview["id"], path=str(target), quality=quality, bytes=target.stat().st_size)
