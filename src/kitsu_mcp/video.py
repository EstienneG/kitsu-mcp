"""Movie previews: download and cache, probe, frame lookup and image composition.

Decoding needs the optional `video` extra (PyAV, which bundles ffmpeg, and Pillow). Both are imported
lazily so the base install works without them; `require()` turns their absence into a clear ToolError.
Frames are numbered from 1, like Kitsu's player; timecodes are HH:MM:SS:FF of the frame's start.
"""

from __future__ import annotations

import io
import math
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from kitsu_mcp.client import NotFoundError, get_client

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

Quality = Literal["low", "original"]
ImageFormat = Literal["jpeg", "png"]

VIDEO_EXTENSIONS = frozenset(
    {"mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg", "wmv", "flv", "mxf", "ogv", "3gp", "ts", "mts"}
)
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "tif", "tiff", "exr", "bmp", "webp", "psd", "tga", "svg"})

MAX_FRAMES = 16
"""Frames per tool call: each image costs model context."""
MAX_SHEET_SIDE = 1568
"""Longest side of a composed image (contact sheet, comparison), in pixels."""
MAX_FRAME_SIDE = 1280
"""Longest side of a single frame image."""
_TILE_WIDTH = 384
_JPEG_QUALITY = 80

INSTALL_HINT = (
    "Video tools need the optional video extra (PyAV and Pillow). Install kitsu-mcp[video], e.g. run the "
    "server with `uvx --from 'kitsu-mcp[video]' kitsu-mcp` or `pip install 'kitsu-mcp[video]'`."
)


# --- optional dependencies -----------------------------------------------------------------------


def available() -> bool:
    try:
        require()
    except ToolError:
        return False
    return True


def require() -> None:
    """Raise a ToolError naming the extra to install when PyAV or Pillow is missing."""
    try:
        import av  # noqa: F401
        import PIL.Image  # noqa: F401
    except ImportError as error:
        raise ToolError(INSTALL_HINT) from error


# --- Kitsu metadata ------------------------------------------------------------------------------


def extension(preview: dict) -> str:
    return (preview.get("extension") or "").lower().lstrip(".")


def is_video(preview: dict) -> bool:
    """Kitsu's `is_movie` flag is unreliable (False on real mp4s): trust the extension, fall back to the flag."""
    ext = extension(preview)
    if ext in VIDEO_EXTENSIONS:
        return True
    if ext in IMAGE_EXTENSIONS:
        return False
    return bool(preview.get("is_movie"))


def check_id(value: str, label: str = "ID") -> str:
    """IDs end up in URLs and cache file names: reject anything but letters, digits, - and _."""
    if not re.fullmatch(r"[\w-]{1,100}", value or ""):
        raise ToolError(f"Invalid {label}: {value!r}")
    return value


def preview_file(preview_file_id: str) -> dict:
    return get_client().get(f"data/preview-files/{check_id(preview_file_id, 'preview file ID')}")


def resolve_preview(preview_file_id: str | None, entity_id: str | None) -> dict:
    """The preview-file record of a preview file ID, or of an asset/shot's current preview. Must be a movie."""
    if bool(preview_file_id) == bool(entity_id):
        raise ToolError("Pass exactly one of preview_file_id or entity_id")
    if entity_id:
        entity = get_client().get(f"data/entities/{check_id(entity_id, 'entity ID')}")
        preview_file_id = entity.get("preview_file_id")
        if not preview_file_id:
            raise ToolError(f"{entity.get('name') or entity_id} has no preview")
    assert preview_file_id
    preview = preview_file(preview_file_id)
    if not is_video(preview):
        raise ToolError(
            f"Preview file {preview_file_id} is not a video (extension {extension(preview) or 'unknown'}); "
            "use get_preview_file with show=True to see it"
        )
    return preview


def task_videos(task_id: str) -> list[dict]:
    """Movie previews of a task, newest revision first."""
    previews = get_client().get(f"data/tasks/{check_id(task_id, 'task ID')}/previews")
    videos = [p for p in previews if is_video(p)]
    return sorted(videos, key=lambda p: (p.get("revision") or 0, p.get("created_at") or ""), reverse=True)


def movie_route(preview: dict, quality: Quality) -> str:
    preview_id = check_id(preview["id"], "preview file ID")
    if quality == "low":
        return f"movies/low/preview-files/{preview_id}.mp4"
    return f"movies/originals/preview-files/{preview_id}.{check_id(extension(preview) or 'mp4', 'extension')}"


def file_extension(preview: dict, quality: Quality) -> str:
    return "mp4" if quality == "low" else (extension(preview) or "mp4")


# --- download cache ------------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def cache_dir() -> Path:
    configured = get_client().settings.video_cache_dir
    path = Path(configured).expanduser() if configured else Path(tempfile.gettempdir()) / "kitsu-mcp-videos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def max_download_bytes() -> int:
    return int(get_client().settings.video_max_mb * 2**20)


def fetch(preview: dict, quality: Quality = "low") -> Path:
    """Local path of a preview's movie, downloading it into the cache on first use."""
    directory = cache_dir()
    path = directory / f"{check_id(preview['id'])}_{quality}.{file_extension(preview, quality)}"
    with _key_lock(str(path)):
        if path.exists():
            os.utime(path)  # mark as recently used
            return path
        limit = max_download_bytes()
        known = (preview.get("data") or {}).get("original_file_size") if quality == "original" else None
        if known and known > limit:
            raise ToolError(
                f"The original movie is {known / 2**20:.0f} MB, over the {limit / 2**20:.0f} MB cap "
                "(KITSU_VIDEO_MAX_MB); use quality='low'"
            )
        partial = directory / f".{path.name}.{uuid.uuid4().hex}.part"
        route = movie_route(preview, quality)
        try:
            get_client().download(route, partial, max_bytes=limit)
            partial.replace(path)
        except NotFoundError as error:
            hint = " Try quality='original'." if quality == "low" else ""
            raise ToolError(f"Kitsu has no {quality} movie for preview file {preview['id']}.{hint}") from error
        finally:
            partial.unlink(missing_ok=True)
    evict(keep=path)
    return path


def evict(keep: Path | None = None) -> None:
    """Delete the least recently used movies until the cache fits KITSU_VIDEO_CACHE_MB."""
    budget = get_client().settings.video_cache_mb * 2**20
    files = []
    for f in cache_dir().iterdir():
        if f.is_file() and not f.name.startswith(".") and f != keep:
            try:
                stat = f.stat()
            except FileNotFoundError:
                continue
            files.append((stat.st_mtime, stat.st_size, f))
    total = sum(size for _, size, _ in files) + (keep.stat().st_size if keep and keep.exists() else 0)
    for _, size, f in sorted(files):
        if total <= budget:
            break
        f.unlink(missing_ok=True)  # open readers keep their handle on POSIX
        total -= size


# --- probing and frame addressing ----------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    codec: str | None
    width: int
    height: int
    fps: float
    duration: float
    frame_count: int


def probe(path: Path) -> Probe:
    """Read the stream metadata of a movie file."""
    require()
    import av
    import av.error

    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ToolError("The movie has no video stream")
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.guessed_rate or stream.base_rate
            fps = float(rate) if rate else 25.0
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = container.duration / 1_000_000
            else:
                duration = 0.0
            frame_count = stream.frames or round(duration * fps)
            return Probe(
                codec=stream.codec_context.name,
                width=stream.codec_context.width,
                height=stream.codec_context.height,
                fps=round(fps, 3),
                duration=round(duration, 3),
                frame_count=max(int(frame_count), 1),
            )
    except av.error.FFmpegError as error:
        raise ToolError(f"Could not read the movie: {error}") from error


def nominal_fps(fps: float) -> int:
    return max(round(fps), 1)


def timecode(frame: int, fps: float) -> str:
    """HH:MM:SS:FF at the start of a 1-based frame (Kitsu's display)."""
    rate = nominal_fps(fps)
    index = max(frame - 1, 0)
    seconds, ff = divmod(index, rate)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{ff:02d}"


def frame_at(seconds: float, fps: float) -> int:
    """1-based frame shown at a time in seconds."""
    return math.floor(seconds * fps + 1e-6) + 1


_TIMECODE = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[:;](\d{1,3})")
_CLOCK = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)")
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)?", re.IGNORECASE)


def parse_moment(spec: int | float | str, fps: float, frame_count: int) -> int:
    """A 1-based frame from a frame number, timecode, time or percentage.

    Accepted: 37 or "37" or "f37" (frame number), "00:00:01:12" (HH:MM:SS:FF timecode), "0:01.5" or
    "00:00:01.5" (M:SS / H:MM:SS time), 1.5 or "1.5s" (seconds), "50%" (of the duration).
    """
    frame: int
    if isinstance(spec, bool):
        raise ToolError(f"Invalid frame reference: {spec!r}")
    if isinstance(spec, int):
        frame = spec
    elif isinstance(spec, float):
        frame = frame_at(spec, fps)
    else:
        text = spec.strip().lower()
        if m := re.fullmatch(r"(?:f|fr|frame)?\s*#?\s*(\d+)", text):
            frame = int(m[1])
        elif m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", text):
            percent = float(m[1])
            if percent > 100:
                raise ToolError(f"Percentage over 100: {spec!r}")
            frame = round(percent / 100 * (frame_count - 1)) + 1
        elif m := _TIMECODE.fullmatch(text):
            rate = nominal_fps(fps)
            hours, minutes, seconds, ff = (int(g) for g in m.groups())
            if ff >= rate:
                raise ToolError(f"Frame field {ff} of {spec!r} is not below the frame rate ({rate} fps)")
            frame = (hours * 3600 + minutes * 60 + seconds) * rate + ff + 1
        elif m := _CLOCK.fullmatch(text):
            frame = frame_at(int(m[1] or 0) * 3600 + int(m[2]) * 60 + float(m[3]), fps)
        elif m := _SECONDS.fullmatch(text):
            frame = frame_at(float(m[1]), fps)
        else:
            raise ToolError(
                f"Unrecognized frame reference {spec!r}: use a frame number (37), a timecode (00:00:01:12), "
                "seconds (1.5s) or a percentage (50%)"
            )
    if not 1 <= frame <= frame_count:
        raise ToolError(f"{spec!r} is outside the movie (frames 1-{frame_count})")
    return frame


def parse_moments(specs: list[int | float | str], fps: float, frame_count: int) -> list[int]:
    if not specs:
        raise ToolError("Give at least one frame reference")
    if len(specs) > MAX_FRAMES:
        raise ToolError(f"At most {MAX_FRAMES} frames per call (got {len(specs)})")
    return [parse_moment(s, fps, frame_count) for s in specs]


def even_frames(n: int, frame_count: int) -> list[int]:
    """`n` evenly spaced frames, each in the middle of its slice of the movie."""
    check_count(n)
    return sorted({min(int((i + 0.5) * frame_count / n) + 1, frame_count) for i in range(n)})


def check_count(n: int) -> None:
    if not 1 <= n <= MAX_FRAMES:
        raise ToolError(f"n must be between 1 and {MAX_FRAMES}")


@dataclass(frozen=True)
class Reference:
    frame: int
    source: str
    """The text it was found in (e.g. 'v2 00:00:01:00 (25)', 'frame 30') or 'annotation'."""
    revision: int | None = None
    """Revision named in a Kitsu timecode tag."""


_KITSU_TAG = re.compile(r"v(\d+) (?:\d+:)?\d+:\d+[.:]\d+ \((\d+)\)")
_TEXT_TIMECODE = re.compile(r"(?<![\d:])(\d{1,2}:\d{2}:\d{2}[:;]\d{1,2})(?![\d:])")
_TEXT_FRAME = re.compile(r"\b(?:frames?|frm|fr|f|images?|img)\s*#?\s*(\d{1,6})\b", re.IGNORECASE)
_TEXT_SECONDS = re.compile(r"(?<![\w.:])(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", re.IGNORECASE)


def find_references(text: str | None, fps: float, frame_count: int) -> list[Reference]:
    """Frames a comment points at: Kitsu's `v6 00:00:01:12 (37)` tags, timecodes, 'frame 37', '1.5s'.

    Out-of-range references are dropped.
    """
    refs: list[Reference] = []
    if not text:
        return refs
    for m in _KITSU_TAG.finditer(text):
        refs.append(Reference(frame=int(m[2]), source=m[0], revision=int(m[1])))
    rest = _KITSU_TAG.sub(" ", text)
    for pattern in (_TEXT_TIMECODE, _TEXT_FRAME, _TEXT_SECONDS):
        for m in pattern.finditer(rest):
            spec = m[1] if pattern is not _TEXT_SECONDS else f"{m[1]}s"
            try:
                refs.append(Reference(frame=parse_moment(spec, fps, frame_count), source=m[0].strip()))
            except ToolError:
                continue
        rest = pattern.sub(" ", rest)
    return [r for r in refs if 1 <= r.frame <= frame_count]


def annotation_frames(preview: dict, fps: float) -> list[int]:
    """1-based frames with drawings on a preview file. Kitsu keys annotations by time (seconds)."""
    frames = set()
    for annotation in preview.get("annotations") or []:
        if not isinstance(annotation, dict):
            continue
        objects = (annotation.get("drawing") or {}).get("objects")
        if objects == []:
            continue  # a drawing that was erased
        if isinstance(annotation.get("time"), int | float):
            frames.add(round(annotation["time"] * fps) + 1)
        elif str(annotation.get("frame", "")).isdigit():
            frames.add(int(annotation["frame"]) + 1)
    return sorted(frames)


# --- decoding ------------------------------------------------------------------------------------


def grab(path: Path, frames: list[int], info: Probe) -> dict[int, PILImage]:
    """Decode the given 1-based frames. Seeks to the keyframe before each and decodes forward."""
    require()
    import av
    import av.error

    wanted = sorted(set(frames))
    images: dict[int, PILImage] = {}
    try:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            time_base = float(stream.time_base or 0) or 1 / 90000
            start = stream.start_time or 0
            decoder = None
            position = -1  # 0-based index of the last decoded frame
            last = None
            for frame in wanted:
                target = frame - 1
                # Seek unless the target is a short decode ahead of where we are.
                if decoder is None or target <= position or target - position > 2 * info.fps:
                    container.seek(start + int(target / info.fps / time_base), stream=stream, backward=True)
                    decoder = container.decode(stream)
                for decoded in decoder:
                    last = decoded
                    if decoded.pts is None:
                        position += 1
                    else:
                        position = round((decoded.pts - start) * time_base * info.fps)
                    if position >= target:
                        images[frame] = decoded.to_image()
                        break
                else:
                    decoder = None  # stream ended before the target: show the last frame
                    if last is not None:
                        images[frame] = last.to_image()
    except av.error.FFmpegError as error:
        raise ToolError(f"Could not decode the movie: {error}") from error
    missing = [f for f in wanted if f not in images]
    if missing:
        raise ToolError(f"Could not decode frames {missing}")
    return images


# --- images --------------------------------------------------------------------------------------


def _font(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def _bar_height(width: int) -> int:
    return max(14, min(24, width // 18)) + 6


def labelled(image: PILImage, label: str, width: int, height: int) -> PILImage:
    """The image fitted in width x height (letterboxed), with a caption bar underneath."""
    from PIL import Image as PIL
    from PIL import ImageDraw

    bar = _bar_height(width)
    tile = PIL.new("RGB", (width, height + bar), (24, 24, 24))
    fitted = image.copy()
    fitted.thumbnail((width, height))
    tile.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    draw = ImageDraw.Draw(tile)
    draw.text((4, height + 3), label, fill=(240, 240, 240), font=_font(bar - 6))
    return tile


def frame_label(frame: int, fps: float, prefix: str = "") -> str:
    return f"{prefix}#{frame}  {timecode(frame, fps)}"


def single(image: PILImage, label: str, max_side: int) -> PILImage:
    side = max(64, min(max_side, MAX_FRAME_SIDE))
    scale = min(1.0, side / max(image.width, image.height))
    return labelled(image, label, max(1, round(image.width * scale)), max(1, round(image.height * scale)))


def grid(
    cells: list[tuple[PILImage, str] | None],
    columns: int,
    aspect: float,
    headers: list[str] | None = None,
) -> PILImage:
    """Lay labelled tiles out in a grid that fits within MAX_SHEET_SIDE. `aspect` is height / width."""
    from PIL import Image as PIL
    from PIL import ImageDraw

    rows = math.ceil(len(cells) / columns)
    gap = 4
    header = 0
    # Never upscale small movies (but keep tiles wide enough for their label).
    source_width = max((cell[0].width for cell in cells if cell), default=_TILE_WIDTH)
    width = min(_TILE_WIDTH, max(source_width, 160), (MAX_SHEET_SIDE - gap * (columns + 1)) // columns)
    # Shrink tiles until the sheet is no taller than the cap either.
    while width > 48:
        header = _bar_height(width) if headers else 0
        height = round(width * aspect)
        if header + rows * (height + _bar_height(width) + gap) + gap <= MAX_SHEET_SIDE:
            break
        width -= 8
    height = max(1, round(width * aspect))
    tile_h = height + _bar_height(width)
    sheet = PIL.new("RGB", (columns * (width + gap) + gap, header + rows * (tile_h + gap) + gap), (0, 0, 0))
    if headers:
        draw = ImageDraw.Draw(sheet)
        for c, text in enumerate(headers):
            draw.text((gap + c * (width + gap) + 4, 3), text, fill=(255, 220, 120), font=_font(header - 6))
    for i, cell in enumerate(cells):
        if cell is None:
            continue
        r, c = divmod(i, columns)
        sheet.paste(
            labelled(cell[0], cell[1], width, height), (gap + c * (width + gap), header + gap + r * (tile_h + gap))
        )
    return sheet


def encode(image: PILImage, fmt: ImageFormat = "jpeg") -> Image:
    buffer = io.BytesIO()
    if fmt == "png":
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return Image(data=buffer.getvalue(), format=fmt)
