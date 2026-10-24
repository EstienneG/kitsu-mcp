import pytest
from fastmcp import Client

from kitsu_mcp.server import mcp


async def test_get_preview_returns_image(fake):
    async with Client(mcp) as client:
        result = await client.call_tool("get_preview", {"entity_id": "a-hero"})
    assert [c.type for c in result.content] == ["image"]
    assert ("GET", "pictures/thumbnails/preview-files/pf-hero.png", None) in fake.calls


async def test_get_preview_of_a_video_points_to_the_video_tools(fake):
    async with Client(mcp) as client:
        result = await client.call_tool("get_preview", {"entity_id": "s-1"})
        shown = await client.call_tool("get_preview_file", {"preview_file_id": "pf-sh010", "show": True})
    for r in (result, shown):
        assert [c.type for c in r.content] == ["image", "text"]
        assert "get_video_contact_sheet" in r.content[1].text


async def test_get_preview_without_preview(call):
    assert await call("get_preview", entity_id="a-forest") == "This entity has no preview."


async def test_get_preview_file_metadata(call):
    meta = await call("get_preview_file", preview_file_id="pf-sh010")
    assert (meta["revision"], meta["is_movie"], meta["extension"], meta["is_video"]) == (1, True, "mp4", True)
    assert "get_video_frames" in meta["note"]
    image = await call("get_preview_file", preview_file_id="pf-hero")
    assert (image["is_video"], image["note"]) == (False, None)


async def test_get_preview_file_detects_video_by_extension(call, fake):
    fake.data["preview_files"]["pf-sh010"]["is_movie"] = False  # Kitsu reports False on real mp4s
    assert (await call("get_preview_file", preview_file_id="pf-sh010"))["is_video"]


async def test_list_task_previews(call):
    assert [p["id"] for p in await call("list_task_previews", task_id="t-hero-mod")] == ["pf-hero"]


async def test_download_previews(call, fake, tmp_path):
    fake.data["assets"][0]["name"] = "Hero/../evil"
    result = await call("download_previews", project="Demo Short", dest_dir=str(tmp_path), size="thumbnail")
    assert {s["id"] for s in result["saved"]} == {"a-hero", "s-1"}
    assert result["skipped"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Hero_.._evil_a-hero.png", "SH010_s-1.png"]


async def test_playlists(call):
    playlists = await call("list_playlists", project="Demo Short")
    assert [(p["name"], p["task_type"]) for p in playlists] == [("Dailies", "Animation")]
    detail = await call("get_playlist", playlist_id="pl-1")
    assert detail["items"] == [{"entity_id": "s-1", "entity": "SH010", "preview_file_id": "pf-sh010"}]


@pytest.mark.parametrize("name", ["get_preview", "get_preview_file", "list_task_previews", "list_playlists"])
async def test_preview_tools_are_read_only(name):
    tool = await mcp.get_tool(name)
    assert tool.annotations.read_only_hint


async def test_list_playlists_reads_every_page(call, fake):
    template = fake.data["playlists"][0]
    fake.data["playlists"] = [
        {**template, "id": f"pl-{i}", "name": f"P{i}", "updated_at": f"2026-10-{i % 28 + 1:02d}T00:00:00"}
        for i in range(45)
    ]
    playlists = await call("list_playlists", project="p-1")
    assert len(playlists) == 45
    assert len({p["id"] for p in playlists}) == 45


async def test_download_previews_keeps_existing_files(call, fake, tmp_path):
    existing = tmp_path / "Hero_a-hero.png"
    existing.write_bytes(b"mine")
    result = await call("download_previews", project="p-1", dest_dir=str(tmp_path), entity_kind="assets")
    assert result["saved"] == [] and result["skipped"] == 2
    assert existing.read_bytes() == b"mine"
    result = await call(
        "download_previews", project="p-1", dest_dir=str(tmp_path), entity_kind="assets", overwrite=True
    )
    assert [s["id"] for s in result["saved"]] == ["a-hero"]
    assert existing.read_bytes() != b"mine"
