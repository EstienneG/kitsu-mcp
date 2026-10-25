"""Movie previews: download and cache, probe, frame lookup and image composition.

Decoding needs the optional `video` extra (PyAV, which bundles ffmpeg, and Pillow). Both are imported
lazily so the base install works without them; `require()` turns their absence into a clear ToolError.
Frames are numbered from 1, like Kitsu's player; timecodes are HH:MM:SS:FF of the frame's start. Frame
numbers are positions on the movie's nominal frame rate grid (time x fps), which is what timecodes count;
for variable frame rate footage they can differ from a count of decoded frames.
"""

from __future__ import annotations

import contextlib
import io
import math
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image

from kitsu_mcp.kitsu import validation
from kitsu_mcp.kitsu.client import NotFoundError, get_client

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
    """IDs end up in URLs and cache file names: they must be Kitsu IDs (UUIDs)."""
    if not isinstance(value, str) or not validation.id_pattern.fullmatch(value):
        raise ToolError(f"Invalid {label}: {value!r} (Kitsu IDs look like 'a1b2c3d4-...')")
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
            "use get_preview to see it"
        )
    if is_broken(preview):
        raise ToolError(f"Preview file {preview_file_id} is marked broken in Kitsu (its processing failed)")
    return preview


def is_broken(preview: dict) -> bool:
    """Kitsu marks previews whose processing failed as `broken`; they have no playable movie or image."""
    return preview.get("status") == "broken"


def task_videos(task_id: str) -> list[dict]:
    """Playable movie previews of a task, newest revision first; within a revision, by upload position.

    A revision can hold several files (position 1, 2, ...), e.g. a playblast and a render. Kitsu shows
    position 1 as the revision's main file.
    """
    previews = get_client().get(f"data/tasks/{check_id(task_id, 'task ID')}/previews")
    videos = [p for p in previews if is_video(p) and not is_broken(p)]
    return sorted(
        videos,
        key=lambda p: (-(p.get("revision") or 0), p.get("position") or 1, p.get("created_at") or ""),
    )


def latest_revisions(task_id: str, count: int) -> list[dict]:
    """The main movie (lowest position) of each of the `count` latest distinct revisions, newest first."""
    picked: dict[int, dict] = {}
    for preview in task_videos(task_id):
        picked.setdefault(preview.get("revision") or 0, preview)
        if len(picked) == count:
            break
    return list(picked.values())


def original_size(preview: dict) -> int | None:
    """Bytes of the uploaded file. Zou's `file_size` is the original's size; `data.original_file_size`
    is not reliable (it can be far smaller than the uploaded file)."""
    for value in (preview.get("file_size"), (preview.get("data") or {}).get("original_file_size")):
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def movie_route(preview: dict, quality: Quality) -> str:
    preview_id = check_id(preview["id"], "preview file ID")
    folder = "low" if quality == "low" else "originals"
    return f"movies/{folder}/preview-files/{preview_id}.{file_extension(preview, quality)}"


def file_extension(preview: dict, quality: Quality) -> str:
    """Extension of the movie file: the low-res encode is always mp4. Kitsu's value ends up in URLs and
    file names, so it must be a short alphanumeric extension."""
    if quality == "low":
        return "mp4"
    ext = extension(preview) or "mp4"
    if not re.fullmatch(r"[a-z0-9]{1,8}", ext):
        raise ToolError(f"Unexpected file extension {ext!r} on preview file {preview.get('id')}")
    return ext


# --- download cache ------------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_recent: dict[Path, float] = {}
"""Cache files handed out by fetch() and when: a tool decodes them after fetching (compare_revisions
holds two), so eviction leaves recently fetched files alone."""
IN_USE_SECONDS = 600


def _key_lock(key: str) -> threading.Lock:
    with _locks_guard:
        if len(_locks) > 1000:  # forget idle locks so the table cannot grow without bound
            for name, lock in list(_locks.items()):
                if not lock.locked():
                    del _locks[name]
        return _locks.setdefault(key, threading.Lock())


def _mark_used(path: Path) -> None:
    now = time.monotonic()
    with _locks_guard:
        _recent[path] = now
        for old in [p for p, t in _recent.items() if now - t > IN_USE_SECONDS]:
            del _recent[old]


def _in_use(path: Path) -> bool:
    with _locks_guard:
        stamp = _recent.get(path)
    return stamp is not None and time.monotonic() - stamp <= IN_USE_SECONDS


def _cache_root() -> Path:
    configured = get_client().settings.video_cache_dir
    return Path(configured).expanduser() if configured else Path(tempfile.gettempdir()) / "kitsu-mcp-videos"


def cache_dir() -> Path:
    """The movie cache of the current caller. Over HTTP each Kitsu user gets their own folder, so a movie
    fetched for one person is never served to another without Kitsu checking their access."""
    client = get_client()
    path = _private_dir(_cache_root(), parents=True)
    if client.credentials is not None:
        path = _private_dir(_private_dir(path / "users") / client.credentials.user_key[:32])
    return path


def _private_dir(path: Path, parents: bool = False) -> Path:
    """Create `path` (or accept it if it exists) as a real directory owned by us and readable only by us.

    A shared temp dir could hold a folder someone else created first, world-writable or a symlink, to plant
    or read movies; refuse it rather than use it.
    """
    path.mkdir(mode=0o700, parents=parents, exist_ok=True)
    if os.name != "posix":
        return path
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ToolError(
            f"Video cache folder {path} is not a directory owned by this server's user; remove it or set "
            "KITSU_VIDEO_CACHE_DIR to a private folder"
        )
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)
    return path


def _cached_movies() -> list[Path]:
    """Every cached movie: the server's own and, over HTTP, every user's. KITSU_VIDEO_CACHE_MB caps them together."""
    root = _cache_root()
    if not root.is_dir():
        return []
    users = root / "users"
    folders = [root, *(d for d in users.iterdir() if d.is_dir())] if users.is_dir() else [root]
    return [f for d in folders for f in d.iterdir() if f.is_file() and not f.name.startswith(".")]


def max_download_bytes() -> int:
    return int(get_client().settings.video_max_mb * 2**20)


def fetch(preview: dict, quality: Quality = "low") -> Path:
    """Local path of a preview's movie, downloading it into the cache on first use."""
    path = cache_dir() / f"{check_id(preview['id'])}_{quality}.{file_extension(preview, quality)}"
    with _key_lock(str(path)):
        if path.exists():
            os.utime(path)  # mark as recently used
        else:
            _download(preview, quality, path)
        _mark_used(path)
    # Also on cache hits, so a cache over budget shrinks once its files are no longer in use.
    evict(keep=path)
    return path


def _download(preview: dict, quality: Quality, path: Path) -> None:
    """Download a movie to `path` through a temporary file (never leaves a partial file behind)."""
    limit = max_download_bytes()
    known = original_size(preview) if quality == "original" else None
    if known and known > limit:
        raise ToolError(
            f"The original movie is {known / 2**20:.0f} MB, over the {limit / 2**20:.0f} MB cap "
            "(KITSU_VIDEO_MAX_MB); use quality='low'"
        )
    partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    # Another user's eviction may have removed this (then empty) per-user folder since cache_dir().
    _private_dir(path.parent)
    try:
        get_client().download(movie_route(preview, quality), partial, max_bytes=limit)
        partial.replace(path)
    except NotFoundError as error:
        hint = " Try quality='original'." if quality == "low" else ""
        raise ToolError(f"Kitsu has no {quality} movie for preview file {preview['id']}.{hint}") from error
    finally:
        partial.unlink(missing_ok=True)


def evict(keep: Path | None = None) -> None:
    """Delete the least recently used movies until the cache (all users together) fits KITSU_VIDEO_CACHE_MB.

    Files fetched in the last IN_USE_SECONDS may still be decoding and are kept, so the cache can go
    over budget for a while; they are evicted on a later call.
    """
    budget = get_client().settings.video_cache_mb * 2**20
    files = []
    for f in _cached_movies():
        if f != keep and not _in_use(f):
            try:
                stat = f.stat()
            except FileNotFoundError:
                continue
            files.append((stat.st_mtime, stat.st_size, f))
    total = sum(size for _, size, _ in files) + (keep.stat().st_size if keep and keep.exists() else 0)
    for _, size, f in sorted(files):
        if total <= budget:
            break
        try:
            f.unlink(missing_ok=True)  # open readers keep their handle on POSIX
        except OSError:
            continue  # e.g. open on Windows; try again next time
        total -= size
        if f.parent.parent.name == "users":
            with contextlib.suppress(OSError):
                f.parent.rmdir()  # a user's folder once empty (fails harmlessly if not)


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
                # The container's duration runs from time 0, so it includes a non-zero start offset.
                duration = max(container.duration - (container.start_time or 0), 0) / 1_000_000
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
    "00:00:01.5" (M:SS / H:MM:SS time), 1.5 or "1.5s" (seconds; a whole number like 27.0 is a frame,
    use "27s" for seconds), "50%" (of the duration).
    """
    frame: int
    if isinstance(spec, bool):
        raise ToolError(f"Invalid frame reference: {spec!r}")
    if isinstance(spec, float) and spec.is_integer():
        spec = int(spec)  # JSON clients may send 27.0 for frame 27; whole seconds need "27s"
    if isinstance(spec, int):
        frame = spec
    elif isinstance(spec, float):
        frame = frame_at(spec, fps)
    else:
        text = spec.strip().lower()
        if m := re.fullmatch(r"(?:f|fr|frame)?\s*#?\s*(\d+)(?:\.0+)?", text):
            frame = int(m[1])  # "37" and "37.0" are frames, like the numbers 37 and 37.0
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
    return list(dict.fromkeys(parse_moment(s, fps, frame_count) for s in specs))


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
# "frame 12", "frames 12-20", "frames 3, 4 et 5", "fr 12", "f12", "f 12" (a bare f only lowercase and not
# in a word or URL path, so "F1 car" and "x.com/f12" are not frames).
_TEXT_FRAME = re.compile(
    r"(?:(?<![\w/])(?i:frames?|frm|fr)\s*#?\s*|(?<![\w/])f\s?#?)"
    # Further numbers in a list or range, unless they are really a time ("f 12, 2.5s").
    # The first number must not be followed by a decimal: "f2.8" is a camera f-stop, not frame 2.
    r"(\d{1,6}(?![.,]?\d)(?:\s*(?:[-–,]|\bto\b|\bà\b|\bet\b|\band\b)\s*\d{1,6}(?![.,]\d|\s*(?i:s|sec|:)\b|\d))*)\b"
)
_FRAME_NUMBER = re.compile(r"\d{1,6}")
# "1.5s", "1,5 s", "2 sec", "10 secondes"; not "s'il" / "s’il".
_TEXT_SECONDS = re.compile(
    r"(?<![\w.,:/])(\d+(?:[.,]\d+)?)"
    # A bare "s" glued to 20, 30, ..., 90 or a year is a decade ("the 90s look", "1980s"), not seconds.
    r"(?:\s*(?i:secondes?|seconds?|secs?)|\s+(?i:s)|(?<!(?<!\d)[2-9]0)(?<!\d{3}0)(?i:s))(?![\w'’])"
)
# "at 0:02", "à 1:30", "vers 0:05", "around 0:02.5": a M:SS movie time only after such a word, so clock
# times ("à 12:30 on fait la review") are rare false positives and usually past the movie's end anyway.
_TEXT_CLOCK = re.compile(r"(?i:\b(?:at|à|a|vers|around|to)\s+)(\d{1,2}:\d{2}(?:[.,]\d+)?)(?![\d:])")


def find_references(text: str | None, fps: float, frame_count: int) -> list[Reference]:
    """Frames a comment points at: Kitsu's `v6 00:00:01:12 (37)` tags, timecodes, 'frame 37', '1.5s'.

    Out-of-range references are dropped, except Kitsu tags (they may be about another revision).
    """
    refs: list[Reference] = []
    if not text:
        return refs
    for m in _KITSU_TAG.finditer(text):
        refs.append(Reference(frame=int(m[2]), source=m[0], revision=int(m[1])))
    rest = _KITSU_TAG.sub(" ", text)
    for pattern in (_TEXT_TIMECODE, _TEXT_FRAME, _TEXT_SECONDS, _TEXT_CLOCK):
        for m in pattern.finditer(rest):
            for spec in _specs(pattern, m[1]):
                try:
                    refs.append(Reference(frame=parse_moment(spec, fps, frame_count), source=m[0].strip()))
                except ToolError:
                    continue
        rest = pattern.sub(" ", rest)
    # Kitsu tags name their own revision, so keep them even past this movie's end: review_video lists
    # them under refers_to_other_revisions.
    return [r for r in refs if r.revision is not None or 1 <= r.frame <= frame_count]


def _specs(pattern: re.Pattern, found: str) -> list[str]:
    """parse_moment inputs for one match: frame lists and ranges give their numbers (a range its two ends)."""
    if pattern is _TEXT_FRAME:
        return _FRAME_NUMBER.findall(found)
    if pattern is _TEXT_SECONDS:
        return [f"{found.replace(',', '.')}s"]
    return [found.replace(",", ".")]


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
                    decoder, position = _seek(container, stream, start, time_base, target, info.fps)
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


def _seek(container, stream, start: int, time_base: float, target: int, fps: float):
    """A decoder positioned at or before `target` (0-based), and the index of the frame before it.

    Seeks to the keyframe before the target. Some formats (MPEG-TS) land after the requested time, even
    when seeking to the very start; then fall back to decoding from the beginning of the file.
    """
    for back in (0.0, 4.0):
        container.seek(start + int(max(target / fps - back, 0.0) / time_base), stream=stream, backward=True)
        decoder = container.decode(stream)
        first = next(decoder, None)
        if first is None:
            continue  # nothing after this point (e.g. inside an MPEG-TS's last GOP): seek further back
        landed = 0 if first.pts is None else round((first.pts - start) * time_base * fps)
        if landed <= target:
            return _chain(first, decoder), landed - 1
    # Seeking on the stream cannot reach the target: rewind the whole input (container time 0, which
    # MPEG-TS honours) and decode from the first frame.
    container.seek(0)
    return container.decode(stream), -1


def _chain(first, rest):
    yield first
    yield from rest


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
    empty_label: str | None = "past end",
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
        r, c = divmod(i, columns)
        if cell is None:
            if empty_label:
                draw = ImageDraw.Draw(sheet)
                x, y = gap + c * (width + gap), header + gap + r * (tile_h + gap)
                draw.text(
                    (x + 8, y + height // 2), empty_label, fill=(150, 150, 150), font=_font(_bar_height(width) - 6)
                )
            continue
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
