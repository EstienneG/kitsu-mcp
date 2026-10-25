"""Video tools, against synthetic movies whose frame colours encode the frame number."""

import base64
import builtins
import io
import json
import os
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from kitsu_mcp import video
from kitsu_mcp.server import mcp
from tests.synthetic_video import FPS, frame_colour, make_movie

av = pytest.importorskip("av", reason="video tests need the video extra (PyAV)")
PIL_Image = pytest.importorskip("PIL.Image", reason="video tests need the video extra (Pillow)")

LOW_V2 = "movies/low/preview-files/pf-sh010.mp4"
LOW_V1 = "movies/low/preview-files/pf-sh010-v1.mp4"
ORIGINAL_V2 = "movies/originals/preview-files/pf-sh010.mp4"


@pytest.fixture(scope="session")
def movies(tmp_path_factory) -> dict[str, bytes]:
    """v2: 72 frames (3 s) at 160x90; v1: 48 frames (2 s) at 128x96. 24 fps, a keyframe per second."""
    folder = tmp_path_factory.mktemp("movies")
    v2 = make_movie(folder / "v2.mp4").read_bytes()
    v1 = make_movie(folder / "v1.mp4", frames=48, size=(128, 96)).read_bytes()
    return {LOW_V2: v2, LOW_V1: v1, ORIGINAL_V2: v2}


@pytest.fixture(autouse=True)
def served(fake, movies, tmp_path):
    fake.movies = dict(movies)
    fake.settings.video_cache_dir = tmp_path / "cache"
    return fake


async def images(name: str, **args) -> tuple[list[str], list]:
    """Call a tool and return (text blocks, decoded PIL images)."""
    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    texts = [c.text for c in result.content if c.type == "text"]
    pictures = [PIL_Image.open(io.BytesIO(base64.b64decode(c.data))) for c in result.content if c.type == "image"]
    return texts, pictures


def frame_shown(picture, box=None) -> int:
    """Which synthetic frame a tile shows, from the colour at its centre (box: left, top, width, height)."""
    left, top, width, height = box or (0, 0, picture.width, picture.height - video._bar_height(picture.width))
    pixel = picture.convert("RGB").getpixel((left + width // 2, top + height // 2))
    colours = [frame_colour(i) for i in range(4 * FPS)]
    distance, index = min((sum(abs(a - b) for a, b in zip(pixel, c, strict=True)), i) for i, c in enumerate(colours))
    assert distance <= 12, f"no frame has colour {pixel}"
    return index + 1


# --- parsing ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "frame"),
    [
        (37, 37),
        ("37", 37),
        ("f37", 37),
        ("frame 37", 37),
        ("00:00:01:12", 37),
        ("00:00:00:00", 1),
        ("00:00:02:23", 72),
        (1.5, 37),
        ("1.5s", 37),
        ("1.5 sec", 37),
        ("0:01.5", 37),
        ("00:00:01.5", 37),
        ("0%", 1),
        ("50%", 37),
        ("100%", 72),
    ],
)
def test_parse_moment(spec, frame):
    assert video.parse_moment(spec, 24.0, 72) == frame


@pytest.mark.parametrize("spec", [0, 73, "00:00:03:00", "4s", "101%", "00:00:01:24", "soon", True])
def test_parse_moment_rejects(spec):
    with pytest.raises(ToolError):
        video.parse_moment(spec, 24.0, 72)


def test_timecode_round_trips():
    for frame in (1, 24, 25, 37, 72, 24 * 3600 + 1):
        assert video.parse_moment(video.timecode(frame, 24.0), 24.0, 10**6) == frame
    assert video.timecode(37, 23.976) == "00:00:01:12"


def test_find_references_in_comment_text():
    refs = video.find_references(
        "v3 00:00:01:12 (37) pops; check 00:00:02:00, frame 10, f 12, 2.5s, and 1:00:00:00 (too late)", 24.0, 72
    )
    assert [(r.frame, r.revision) for r in refs] == [(37, 3), (49, None), (10, None), (12, None), (61, None)]
    assert refs[0].source == "v3 00:00:01:12 (37)"
    assert video.find_references("Looks great, ship it at 10am. v2 is better.", 24.0, 72) == []
    assert video.find_references(None, 24.0, 72) == []


def test_annotation_frames_skip_erased_drawings():
    preview = {
        "annotations": [
            {"time": 1.0, "drawing": {"objects": [{}]}},
            {"time": 0.5, "drawing": {"objects": []}},
            {"frame": 3, "drawing": {"objects": [{}]}},
            "junk",
        ]
    }
    assert video.annotation_frames(preview, 24.0) == [4, 25]
    assert video.annotation_frames({"annotations": None}, 24.0) == []


def test_even_frames_and_cap():
    assert video.even_frames(4, 72) == [10, 28, 46, 64]
    assert video.even_frames(16, 5) == [1, 2, 3, 4, 5]
    with pytest.raises(ToolError, match="between 1 and 16"):
        video.even_frames(17, 72)


@pytest.mark.parametrize(
    ("preview", "expected"),
    [
        ({"extension": "mp4", "is_movie": False}, True),
        ({"extension": "MOV", "is_movie": None}, True),
        ({"extension": ".webm"}, True),
        ({"extension": "png", "is_movie": True}, False),
        ({"extension": "zzz", "is_movie": True}, True),
        ({"extension": None, "is_movie": False}, False),
    ],
)
def test_video_detection_by_extension(preview, expected):
    assert video.is_video(preview) is expected


def test_ids_are_validated(call):
    with pytest.raises(ToolError, match="Invalid"):
        video.check_id("../../etc/passwd")


# --- tools -----------------------------------------------------------------------------------------


async def test_get_video_info(call, served):
    info = await call("get_video_info", entity_id="s-1")
    assert info["preview_file_id"] == "pf-sh010"
    assert (info["codec"], info["width"], info["height"], info["fps"]) == ("h264", 160, 90, FPS)
    assert (info["frame_count"], info["duration"]) == (72, 3.0)
    # Zou's file_size is the uploaded file; data.original_file_size is not trusted.
    assert (info["kitsu_width"], info["kitsu_duration"], info["original_file_size"]) == (1920, 3.0, 9000)
    assert info["quality"] == "low" and info["file_bytes"] == len(served.movies[LOW_V2])


async def test_get_video_info_of_an_annotated_mov_flagged_not_movie(call):
    info = await call("get_video_info", preview_file_id="pf-sh010-v1")
    assert (info["frame_count"], info["annotated_frames"]) == (48, [25])


async def test_video_tools_reject_images_and_missing_previews(call):
    with pytest.raises(ToolError, match="not a video"):
        await call("get_video_info", preview_file_id="pf-hero")
    with pytest.raises(ToolError, match="no preview"):
        await call("get_video_info", entity_id="a-forest")
    with pytest.raises(ToolError, match="exactly one"):
        await call("get_video_info")
    with pytest.raises(ToolError, match="exactly one"):
        await call("get_video_info", preview_file_id="pf-sh010", entity_id="s-1")


async def test_contact_sheet(served):
    texts, pictures = await images("get_video_contact_sheet", preview_file_id="pf-sh010", n=4)
    assert texts == [] and len(pictures) == 1
    sheet = pictures[0]
    assert sheet.format == "JPEG"
    assert max(sheet.size) <= video.MAX_SHEET_SIDE
    # 4 tiles in one row, each 160 px wide (never upscaled) plus 4 px gaps.
    assert sheet.width == 4 * 160 + 5 * 4
    shown = [frame_shown(sheet, (4 + i * 164, 4, 160, 90)) for i in range(4)]
    assert shown == [10, 28, 46, 64]


async def test_contact_sheet_size_cap(served):
    _, pictures = await images("get_video_contact_sheet", preview_file_id="pf-sh010", n=16, format="png")
    assert pictures[0].format == "PNG" and max(pictures[0].size) <= video.MAX_SHEET_SIDE
    with pytest.raises(ToolError, match="between 1 and 16"):
        await images("get_video_contact_sheet", preview_file_id="pf-sh010", n=40)


async def test_get_video_frames(served):
    texts, pictures = await images(
        "get_video_frames", entity_id="s-1", frames=[1, "00:00:01:00", "50%", 2.5, "f72"], max_side=320
    )
    assert texts == []
    assert [frame_shown(p) for p in pictures] == [1, 25, 37, 61, 72]
    assert all(p.width == 160 for p in pictures)  # never upscaled


async def test_get_video_frames_caps_and_errors(call):
    with pytest.raises(ToolError, match="At most 16"):
        await call("get_video_frames", preview_file_id="pf-sh010", frames=list(range(1, 18)))
    with pytest.raises(ToolError, match="outside the movie"):
        await call("get_video_frames", preview_file_id="pf-sh010", frames=[500])
    with pytest.raises(ToolError, match="Unrecognized"):
        await call("get_video_frames", preview_file_id="pf-sh010", frames=["the end"])


async def test_get_video_frames_resizes_large_movies(served, tmp_path):
    served.movies[LOW_V2] = make_movie(tmp_path / "big.mp4", frames=24, size=(1920, 1080)).read_bytes()
    _, pictures = await images("get_video_frames", preview_file_id="pf-sh010", frames=[5], max_side=5000)
    assert pictures[0].width == video.MAX_FRAME_SIDE


async def test_compare_revisions_of_a_task(served):
    texts, pictures = await images("compare_revisions", task_id="t-sh010-anim", n=2)
    summary = json.loads(texts[0])
    assert (summary["a"]["revision"], summary["b"]["revision"]) == (1, 2)
    assert (summary["a"]["duration"], summary["b"]["duration"]) == (2.0, 3.0)
    sheet = pictures[0]
    assert max(sheet.size) <= video.MAX_SHEET_SIDE
    # Two columns (A, B). Moments are 0.75 s and 2.25 s on the longest timeline; 2.25 s is past A's 2 s end,
    # so that cell is left empty ("past end") instead of repeating A's last frame.
    header, height = video._bar_height(160), 120  # tiles keep the taller aspect (v1 is 4:3)
    rows = [header + 4 + r * (height + video._bar_height(160) + 4) for r in range(2)]
    assert frame_shown(sheet, (4, rows[0], 160, height)) == 19
    assert [frame_shown(sheet, (168, y, 160, height)) for y in rows] == [19, 55]
    assert summary["a"]["moments_past_end"] == 1 and "moments_past_end" not in summary["b"]


async def test_compare_revisions_uses_main_file_of_distinct_revisions(served):
    """Revision 2 has two uploads (positions 1 and 2) and revision 3 is broken: compare v1 with v2's main file."""
    texts, _ = await images("compare_revisions", task_id="t-sh010-anim", n=1)
    summary = json.loads(texts[0])
    assert (summary["a"]["preview_file_id"], summary["b"]["preview_file_id"]) == ("pf-sh010-v1", "pf-sh010")


async def test_compare_revisions_explicit_frame_past_end(served):
    texts, _ = await images("compare_revisions", preview_file_a="pf-sh010", preview_file_b="pf-sh010-v1", frames=[60])
    summary = json.loads(texts[0])
    assert summary["b"]["moments_past_end"] == 1 and "moments_past_end" not in summary["a"]


async def test_compare_revisions_explicit_frames(served):
    texts, _ = await images(
        "compare_revisions", preview_file_a="pf-sh010-v1", preview_file_b="pf-sh010", frames=["00:00:01:00", "50%"]
    )
    assert json.loads(texts[0])["a"]["preview_file_id"] == "pf-sh010-v1"


async def test_compare_revisions_errors(call, fake):
    with pytest.raises(ToolError, match="At most 8"):
        await call("compare_revisions", task_id="t-sh010-anim", frames=list(range(1, 10)))
    with pytest.raises(ToolError, match="Pass preview_file_a"):
        await call("compare_revisions", preview_file_a="pf-sh010")
    del fake.data["preview_files"]["pf-sh010-v1"]
    with pytest.raises(ToolError, match="comparing needs two"):
        await call("compare_revisions", task_id="t-sh010-anim")


async def test_review_video(served):
    texts, pictures = await images("review_video", task_id="t-sh010-anim")
    summary = json.loads(texts[0])
    assert (summary["preview_file_id"], summary["revision"]) == ("pf-sh010", 2)
    by_id = {c["text"]: c for c in summary["comments"]}
    approved = by_id["Approved, the v1 00:00:01:12 (37) fix works."]
    # Its tag points at revision 1's timeline, so it is not mapped onto revision 2.
    assert approved["frames"] == [] and approved["refers_to_other_revisions"] == [1]
    assert approved["about_revision"] == 2
    fixed = by_id["v2: fixed the arm at frame 30"]
    assert fixed["frames"] == [{"frame": 30, "timecode": "00:00:01:05"}] and fixed["about_revision"] == 2
    # Posted about revision 1: its frame references belong to v1's timeline and are not placed on v2.
    first = by_id["Arm pops at 00:00:01:00 and again around 2.5s; see drawing."]
    assert first["about_revision"] == 1 and first["frames"] == [] and first["refers_to_other_revisions"] == [1]
    assert summary["frames_shown"] == [30]
    assert [frame_shown(p) for p in pictures] == [30]


async def test_review_video_can_include_other_revisions(served):
    texts, _ = await images("review_video", task_id="t-sh010-anim", include_other_revisions=True)
    summary = json.loads(texts[0])
    first = next(c for c in summary["comments"] if c["text"].startswith("Arm pops"))
    assert [f["frame"] for f in first["frames"]] == [25, 61]
    # A Kitsu tag names its revision explicitly, so it stays off other revisions' timelines.
    approved = next(c for c in summary["comments"] if c["text"].startswith("Approved"))
    assert approved["frames"] == []
    assert summary["frames_shown"] == [30, 25, 61]


async def test_review_video_ignores_image_mentions(served):
    served.data["comments"]["t-sh010-anim"] = [
        {
            "id": "c",
            "created_at": "2026-09-01T00:00:00",
            "text": "See the reference (image 1) for frame 40",
            "previews": [],
        }
    ]
    texts, _ = await images("review_video", task_id="t-sh010-anim")
    assert json.loads(texts[0])["frames_shown"] == [40]


async def test_review_video_of_older_revision_uses_its_annotations(served):
    texts, pictures = await images("review_video", task_id="t-sh010-anim", preview_file_id="pf-sh010-v1", max_frames=2)
    summary = json.loads(texts[0])
    assert summary["annotated_frames"] == [25]
    # On v1's timeline: the v1 tag (37) and the comment posted about v1 (00:00:01:00 = 25; 2.5s is past
    # v1's 48 frames). "frame 30" was posted about v2, so it is not placed on v1.
    assert summary["frames_shown"] == [37, 25] and "frames_omitted" not in summary
    assert len(pictures) == 2


async def test_review_video_without_references(served):
    served.data["comments"]["t-sh010-anim"] = [{"id": "c", "text": "Nice", "previews": []}]
    texts, pictures = await images("review_video", task_id="t-sh010-anim")
    summary = json.loads(texts[0])
    assert summary["frames_shown"] == [] and "get_video_contact_sheet" in summary["note"]
    assert pictures == []


async def test_review_video_errors(call):
    with pytest.raises(ToolError, match="no playable movie preview"):
        await call("review_video", task_id="t-hero-mod")
    with pytest.raises(ToolError, match="max_frames"):
        await call("review_video", task_id="t-sh010-anim", max_frames=0)


async def test_download_video(call, served, tmp_path):
    dest = tmp_path / "out"
    saved = await call("download_video", dest_dir=str(dest), entity_id="s-1")
    path = Path(saved["path"])
    assert path == dest / "sh010_anim_v002_pf-sh010.mp4"
    assert path.read_bytes() == served.movies[LOW_V2] and not saved["skipped"]
    path.write_bytes(b"mine")
    again = await call("download_video", dest_dir=str(dest), preview_file_id="pf-sh010")
    assert again["skipped"] and path.read_bytes() == b"mine"
    replaced = await call("download_video", dest_dir=str(dest), preview_file_id="pf-sh010", overwrite=True)
    assert not replaced["skipped"] and path.read_bytes() == served.movies[LOW_V2]
    original = await call("download_video", dest_dir=str(dest), preview_file_id="pf-sh010", quality="original")
    assert original["path"].endswith("_pf-sh010.mp4") and original["quality"] == "original"


async def test_download_video_annotations():
    tool = await mcp.get_tool("download_video")
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False


@pytest.mark.parametrize(
    "name", ["get_video_info", "get_video_contact_sheet", "get_video_frames", "compare_revisions", "review_video"]
)
async def test_video_tools_are_read_only_and_tagged(name):
    tool = await mcp.get_tool(name)
    assert tool.annotations.read_only_hint
    assert "video" in tool.tags


# --- cache -----------------------------------------------------------------------------------------


async def test_movie_is_downloaded_once_per_quality(call, served):
    await call("get_video_info", preview_file_id="pf-sh010")
    await images("get_video_frames", preview_file_id="pf-sh010", frames=[1])
    await call("get_video_info", preview_file_id="pf-sh010", quality="original")
    movie_calls = [c[1] for c in served.calls if c[1].startswith("movies/")]
    assert movie_calls == [LOW_V2, ORIGINAL_V2]
    cached = sorted(p.name for p in served.settings.video_cache_dir.iterdir())
    assert cached == ["pf-sh010_low.mp4", "pf-sh010_original.mp4"]


async def test_cache_evicts_least_recently_used(call, served, monkeypatch):
    served.settings.video_cache_mb = 0  # only movies in use are kept
    await call("get_video_info", preview_file_id="pf-sh010")
    await call("get_video_info", preview_file_id="pf-sh010-v1")
    # Both were fetched moments ago and may still be decoding: kept despite the budget.
    assert sorted(p.name for p in served.settings.video_cache_dir.iterdir()) == [
        "pf-sh010-v1_low.mp4",
        "pf-sh010_low.mp4",
    ]
    monkeypatch.setattr(video, "IN_USE_SECONDS", -1)  # the grace period has passed
    await call("get_video_info", preview_file_id="pf-sh010-v1")
    assert [p.name for p in served.settings.video_cache_dir.iterdir()] == ["pf-sh010-v1_low.mp4"]


async def test_compare_revisions_with_a_tiny_cache(served):
    """Fetching B must not evict A before A is decoded."""
    served.settings.video_cache_mb = 0
    texts, pictures = await images("compare_revisions", task_id="t-sh010-anim", n=2)
    assert json.loads(texts[0])["a"]["revision"] == 1 and len(pictures) == 1


def test_evict_keeps_recent_files(served):
    folder = video.cache_dir()
    for name, age in (("old_low.mp4", 300), ("mid_low.mp4", 200), ("new_low.mp4", 100)):
        path = folder / name
        path.write_bytes(b"x" * 600_000)
        os.utime(path, (path.stat().st_atime - age, path.stat().st_mtime - age))
    served.settings.video_cache_mb = 1
    video.evict()
    assert sorted(p.name for p in folder.iterdir()) == ["new_low.mp4"]


async def test_size_cap(call, served):
    served.settings.video_max_mb = 0.001  # ~1 KB, smaller than the synthetic movie
    with pytest.raises(ToolError, match="download cap"):
        await call("get_video_info", preview_file_id="pf-sh010")
    assert list(served.settings.video_cache_dir.iterdir()) == []  # no partial file left behind
    # The original is refused from Kitsu's file_size before any download starts.
    served.data["preview_files"]["pf-sh010"]["file_size"] = 10 * 2**20
    served.calls.clear()
    with pytest.raises(ToolError, match="over the"):
        await call("get_video_info", preview_file_id="pf-sh010", quality="original")
    assert not any(path.startswith("movies/") for _, path, _ in served.calls)


async def test_missing_low_movie_suggests_original(call, served):
    del served.movies[LOW_V2]
    with pytest.raises(ToolError, match="quality='original'"):
        await call("get_video_info", preview_file_id="pf-sh010")


# --- extra not installed ---------------------------------------------------------------------------


@pytest.fixture
def without_av(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "av" or name.startswith("av."):
            raise ImportError("No module named 'av'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_video_info", {"preview_file_id": "pf-sh010"}),
        ("get_video_contact_sheet", {"entity_id": "s-1"}),
        ("get_video_frames", {"preview_file_id": "pf-sh010", "frames": [1]}),
        ("compare_revisions", {"task_id": "t-sh010-anim"}),
        ("review_video", {"task_id": "t-sh010-anim"}),
    ],
)
async def test_tools_explain_how_to_install_the_extra(call, served, without_av, name, args):
    with pytest.raises(ToolError, match=r"kitsu-mcp\[video\]"):
        await call(name, **args)
    assert served.calls == []  # fails before touching Kitsu


async def test_without_extra_tools_stay_listed_and_previews_say_so(call, without_av, tmp_path, all_groups):
    names = {t.name for t in await mcp.list_tools()}
    assert {"get_video_info", "review_video", "download_video"} <= names
    assert not video.available()
    meta = await call("get_preview", preview_file_id="pf-sh010", show=False)
    assert "kitsu-mcp[video]" in meta["note"]
    saved = await call("download_video", dest_dir=str(tmp_path), preview_file_id="pf-sh010")
    assert Path(saved["path"]).exists()


async def test_broken_preview(call, served):
    with pytest.raises(ToolError, match="marked broken"):
        await call("get_video_info", preview_file_id="pf-sh010-broken")
    meta = await call("get_preview", preview_file_id="pf-sh010-broken", show=False)
    assert meta["status"] == "broken" and "Broken" in meta["note"] and "get_video" not in meta["note"]
    served.calls.clear()
    with pytest.raises(ToolError, match="marked broken"):
        await call("get_preview", preview_file_id="pf-sh010-broken")
    assert not any(path.startswith("pictures/") for _, path, _ in served.calls)


async def test_get_video_frames_merges_duplicates(served):
    _, pictures = await images("get_video_frames", preview_file_id="pf-sh010", frames=[25, "00:00:01:00", 25.0])
    assert len(pictures) == 1


@pytest.mark.parametrize(
    "text, frames",
    [
        # 24 fps, 72 frames: 1.5 s = frame 37, 2.5 s = frame 61
        ("à 1,5 s le perso saute", [37]),
        ("vers 2,5 sec la main glisse", [61]),
        ("à 1.5s le perso saute", [37]),
        ("2 secondes plus tard", [49]),
        ("10 secondes", []),  # past the 3 s movie
        ("1 s'il te plaît", []),  # French "s'il", not seconds
        ("F1 car, et https://x.com/f12 en référence", []),
        ("frame 12-20 bouge", [12, 20]),
        ("frames 3 and 4", [3, 4]),
        ("frames 3, 4 et 5", [3, 4, 5]),
        ("at 0:02 the arm pops", [49]),
        ("à 12:30 on fait la review", []),  # a clock time, not a movie time (past the end anyway)
        ("v2.1 du rig", []),
        ("image 12", []),
        ("12 frames too long", []),
        ("f12 et frame 30", [12, 30]),
        ("check 00:00:01:00", [25]),
        ("the 90s look", []),  # decades, not seconds
        ("années 80s", []),
        ("the 1980s vibe", []),
        ("2s plus tard", [49]),
        ("f2.8 is too soft", []),  # camera f-stops, not frames
        ("f 2.8", []),
    ],
)
def test_find_references_in_realistic_comments(text, frames):
    assert [r.frame for r in video.find_references(text, 24.0, 72)] == frames


@pytest.mark.parametrize(
    "name, start",
    [
        ("plain.mp4", 0.0),
        ("plain.mov", 0.0),
        ("plain.mkv", 0.0),
        ("plain.ts", 0.0),
        ("late.mp4", 2.0),
        ("late.mkv", 2.0),
    ],
)
def test_frames_are_exact_across_containers_and_start_offsets(tmp_path, name, start):
    """MPEG-TS seeks land after the target and MKV durations include the start offset; both are handled."""
    path = make_movie(tmp_path / name, frames=60, start_seconds=start)
    info = video.probe(path)
    assert (info.frame_count, round(info.duration, 2)) == (60, 2.5)
    wanted = [1, 2, 17, 30, 59, 60]
    one_by_one = {f: video.grab(path, [f], info)[f] for f in wanted}
    batch = video.grab(path, wanted, info)
    for f in wanted:
        raw = (0, 0, one_by_one[f].width, one_by_one[f].height)  # decoded frames have no caption bar
        assert frame_shown(one_by_one[f], raw) == f and frame_shown(batch[f], raw) == f


async def test_original_quality_with_production_ids(call, served, monkeypatch):
    """The fake's readable IDs are widened in conftest; this runs with the real UUID-only check."""
    from kitsu_mcp import validation

    monkeypatch.setattr(validation, "id_pattern", validation.UUID)
    uuid = "1258b106-125e-499a-a19b-a3a3410638e3"
    preview = served.data["preview_files"].pop("pf-sh010")
    served.data["preview_files"][uuid] = {**preview, "id": uuid}
    served.movies[f"movies/originals/preview-files/{uuid}.mp4"] = served.movies[ORIGINAL_V2]
    info = await call("get_video_info", preview_file_id=uuid, quality="original")
    assert info["quality"] == "original" and info["frame_count"] == 72


def test_unexpected_extensions_are_refused():
    for ext in ("../../x", "mp4/../a", "a" * 9):
        with pytest.raises(ToolError, match="Unexpected file extension"):
            video.file_extension({"id": "x", "extension": ext}, "original")
    assert video.file_extension({"id": "x", "extension": "MOV"}, "original") == "mov"


async def test_get_video_frames_checks_count_before_downloading(call, served):
    served.calls.clear()
    with pytest.raises(ToolError, match="At most 16"):
        await call("get_video_frames", preview_file_id="pf-sh010", frames=list(range(1, 18)))
    assert not any(path.startswith("movies/") for _, path, _ in served.calls)


async def test_review_video_checks_the_preview_belongs_to_the_task(call, served):
    with pytest.raises(ToolError, match="belongs to task t-sh010-anim"):
        await call("review_video", task_id="t-hero-mod", preview_file_id="pf-sh010")


def test_decimal_text_frame_numbers():
    assert video.parse_moment("37.0", 24.0, 72) == video.parse_moment(37.0, 24.0, 72) == 37


async def test_review_video_lists_other_revision_tags_past_the_end(served):
    served.data["comments"]["t-sh010-anim"] = [
        {
            "id": "c",
            "created_at": "2026-09-01T00:00:00",
            "text": "v1 00:00:09:00 (217) and v2 00:00:09:00 (217)",
            "previews": [],
        }
    ]
    texts, _ = await images("review_video", task_id="t-sh010-anim")
    summary = json.loads(texts[0])
    comment = summary["comments"][0]
    # v1's frame 217 is past v2's end but still reported as being about v1; v2's own 217 is out of range.
    assert comment["refers_to_other_revisions"] == [1] and comment["frames"] == []
    assert summary["frames_shown"] == []


def test_seconds_glued_to_round_numbers_are_still_seconds():
    """Only 20-90 and years are read as decades: "10s" and "100s" are seconds."""
    assert [r.frame for r in video.find_references("10s puis 100s", 24.0, 5000)] == [241, 2401]
