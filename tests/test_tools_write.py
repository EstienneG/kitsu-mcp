import re

import pytest
from fastmcp.exceptions import ToolError

from kitsu_mcp.server import mcp
from tests.fakes import ALICE, BOB, ST_DONE, ST_WFA, TT_ANIM

WRITE_TOOLS = {
    "add_comment",
    "set_task_status",
    "assign_task",
    "update_task_schedule",
    "log_time",
    "create_playlist",
    "add_to_playlist",
}


@pytest.fixture
def writable():
    mcp.enable(tags={"write"})
    yield
    mcp.disable(tags={"write"})


def writes(fake):
    return [(method, path, data) for method, path, data in fake.calls if method != "GET"]


async def test_write_tools_hidden_by_default():
    assert not WRITE_TOOLS & {t.name for t in await mcp.list_tools()}


async def test_write_tools_are_annotated(writable):
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) >= WRITE_TOOLS
    for name in WRITE_TOOLS:
        assert tools[name].annotations.read_only_hint is False


async def test_add_comment_keeps_status_by_default(call, fake, writable):
    result = await call("add_comment", task_id="t-hero-mod", text="Looks good")
    assert result["message"] == "Comment posted."
    assert writes(fake) == [
        ("POST", "actions/tasks/t-hero-mod/comment", {"task_status_id": ST_WFA, "comment": "Looks good"})
    ]


async def test_add_comment_with_status(call, fake, writable):
    result = await call("add_comment", task_id="t-hero-mod", text="Approved", status="DONE")
    assert result["message"] == "Comment posted; status set to done."
    assert writes(fake)[0][2]["task_status_id"] == ST_DONE


async def test_add_empty_comment_rejected(call, fake, writable):
    with pytest.raises(ToolError, match="empty"):
        await call("add_comment", task_id="t-hero-mod", text="  ")
    assert writes(fake) == []


async def test_set_task_status(call, fake, writable):
    result = await call("set_task_status", task_id="t-hero-mod", status="done")
    assert result["message"] == "Status changed from wfa to done."
    assert result["task"]["entity"] == "Hero"
    assert result["task"]["status"] == "done"


async def test_set_same_status_says_so(call, fake, writable):
    result = await call("set_task_status", task_id="t-hero-mod", status="wfa")
    assert result["message"] == "Status was already wfa; comment posted."


async def test_set_task_status_is_not_marked_idempotent(writable):
    tool = await mcp.get_tool("set_task_status")
    assert tool.annotations.idempotent_hint is False


async def test_write_reported_ok_when_reload_fails(call, fake, writable, monkeypatch):
    original = fake.get

    def get(path, params=None):
        if path == "data/tasks/t-sh020-anim/full" and any(m == "PUT" for m, _, _ in fake.calls):
            raise ToolError("Kitsu error on GET: ServerErrorException")
        return original(path, params)

    monkeypatch.setattr(fake, "get", get)
    result = await call("assign_task", task_id="t-sh020-anim", person="bob")
    assert result["ok"] is True
    assert result["task"] is None
    assert "Could not reload the task" in result["message"]


async def test_set_unknown_status_writes_nothing(call, fake, writable):
    with pytest.raises(ToolError, match="Unknown task status"):
        await call("set_task_status", task_id="t-hero-mod", status="approvedd")
    assert writes(fake) == []


async def test_assign_task(call, fake, writable):
    result = await call("assign_task", task_id="t-sh020-anim", person="bob")
    assert writes(fake) == [("PUT", f"actions/persons/{BOB}/assign", {"task_ids": ["t-sh020-anim"]})]
    assert result["task"]["assignees"] == ["Bob Leroy"]


async def test_update_task_schedule(call, fake, writable):
    result = await call("update_task_schedule", task_id="t-hero-mod", due_date="2026-11-01", estimation_minutes=120)
    assert writes(fake) == [("PUT", "data/tasks/t-hero-mod", {"due_date": "2026-11-01", "estimation": 120})]
    assert (result["task"]["due_date"], result["task"]["estimation"]) == ("2026-11-01", 120)


@pytest.mark.parametrize(
    "args, error",
    [({}, "Nothing to update"), ({"due_date": "next friday"}, "YYYY-MM-DD"), ({"estimation_minutes": -1}, ">= 0")],
)
async def test_update_task_schedule_validation(call, fake, writable, args, error):
    with pytest.raises(ToolError, match=error):
        await call("update_task_schedule", task_id="t-hero-mod", **args)
    assert writes(fake) == []


async def test_log_time_defaults_to_me(call, fake, writable):
    result = await call("log_time", task_id="t-hero-mod", minutes=90, day="2026-10-14")
    assert result["task"]["duration"] == 690
    assert writes(fake) == [
        ("POST", f"actions/tasks/t-hero-mod/time-spents/2026-10-14/persons/{ALICE}/add", {"duration": 90})
    ]


async def test_log_time_bounds(call, fake, writable):
    with pytest.raises(ToolError, match="between 1 and 1440"):
        await call("log_time", task_id="t-hero-mod", minutes=0)


async def test_create_playlist(call, fake, writable):
    result = await call(
        "create_playlist", project="demo short", name=" WRA shots ", for_entity="shot", task_type="anim"
    )
    assert result["ok"] and result["message"] == "Created playlist 'WRA shots' in Demo Short."
    assert writes(fake) == [
        (
            "POST",
            "data/playlists/",
            {
                "name": "WRA shots",
                "project_id": "p-1",
                "for_entity": "shot",
                "for_client": False,
                "task_type_id": TT_ANIM,
            },
        )
    ]
    playlist = result["playlist"]
    assert (playlist["name"], playlist["for_entity"], playlist["task_type"], playlist["items"]) == (
        "WRA shots",
        "shot",
        "Animation",
        [],
    )


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({"project": "Nope"}, "Unknown project 'Nope'"),
        ({"task_type": "Lighting"}, "Unknown task type 'Lighting'"),
        ({"name": "dailies"}, "already has a playlist named 'Dailies' (ID pl-1)"),
        ({"name": "  "}, "name is empty"),
        ({"episode": "EP01"}, "not a TV show"),
    ],
)
async def test_create_playlist_rejects_bad_arguments_before_writing(call, fake, writable, args, error):
    with pytest.raises(ToolError, match=re.escape(error)):
        await call("create_playlist", **{"project": "p-1", "name": "New", "for_entity": "shot", **args})
    assert writes(fake) == []


async def test_create_playlist_in_a_tv_show_needs_the_episode(call, fake, writable):
    fake.data["episodes"] = [{"id": "ep-1", "name": "EP01", "project_id": "p-2"}]
    with pytest.raises(ToolError, match="pass the episode"):
        await call("create_playlist", project="Closed Show", name="New", for_entity="shot")
    with pytest.raises(ToolError, match="Unknown episode 'EP02'"):
        await call("create_playlist", project="Closed Show", name="New", for_entity="shot", episode="EP02")
    assert writes(fake) == []
    await call("create_playlist", project="Closed Show", name="New", for_entity="shot", episode="ep01")
    assert writes(fake)[0][2]["episode_id"] == "ep-1"


async def test_create_playlist_reports_success_when_the_reload_fails(call, fake, writable, monkeypatch):
    from kitsu_mcp.tools import write

    monkeypatch.setattr(write, "playlist_detail", lambda raw: (_ for _ in ()).throw(ToolError("Kitsu is down")))
    result = await call("create_playlist", project="p-1", name="New", for_entity="asset")
    assert result["ok"] and "Could not read it back: Kitsu is down" in result["message"]
    assert result["playlist"] is None


@pytest.fixture
def wra(fake):
    """An empty asset playlist and a shot playlist holding nothing, plus SH020 with an uploaded preview."""
    fake.data["playlists"].append({**fake.data["playlists"][0], "id": "pl-shots", "name": "Shots", "shots": []})
    fake.data["playlists"].append(
        {**fake.data["playlists"][0], "id": "pl-assets", "name": "Assets", "for_entity": "asset", "shots": []}
    )
    return fake


def adds(fake):
    return [data for method, path, data in fake.calls if method == "POST" and path.endswith("/add-entity")]


async def test_add_tasks_to_playlist_with_their_latest_revision(call, wra, writable):
    result = await call("add_to_playlist", playlist_id="pl-shots", task_ids=["t-sh010-anim"])
    # Revision 3 is broken; revision 2's main file is position 1 (pf-sh010), not the render at position 2.
    assert adds(wra) == [{"entity_id": "s-1", "preview_file_id": "pf-sh010"}]
    assert result["added"] == [
        {
            "entity_id": "s-1",
            "entity": "SH010",
            "task_type": "Animation",
            "revision": 2,
            "preview_file_id": "pf-sh010",
        }
    ]
    assert result["message"] == "Added 1 to 'Shots'."
    assert result["playlist"]["items"] == [{"entity_id": "s-1", "entity": "SH010", "preview_file_id": "pf-sh010"}]


async def test_add_entities_to_playlist_with_their_current_preview(call, wra, writable):
    result = await call("add_to_playlist", playlist_id="pl-assets", entity_ids=["a-hero", "a-forest"])
    assert adds(wra) == [{"entity_id": "a-hero", "preview_file_id": "pf-hero"}]
    assert [(e["entity"], e["task_type"], e["revision"]) for e in result["added"]] == [("Hero", "Modeling", 2)]
    assert result["skipped"] == [{"ref": "a-forest", "entity": "Forest", "reason": "no preview uploaded"}]
    assert result["message"] == "Added 1 to 'Assets', skipped 1."


async def test_add_to_playlist_never_adds_twice(call, wra, writable):
    await call("add_to_playlist", playlist_id="pl-assets", task_ids=["t-hero-mod"])
    again = await call("add_to_playlist", playlist_id="pl-assets", task_ids=["t-hero-mod"], entity_ids=["a-hero"])
    assert len(adds(wra)) == 1
    assert [s["reason"] for s in again["skipped"]] == ["already in the playlist"] * 2
    assert len(again["playlist"]["items"]) == 1


async def test_add_task_without_preview_is_skipped(call, wra, writable):
    result = await call("add_to_playlist", playlist_id="pl-shots", task_ids=["t-sh020-anim"])
    assert adds(wra) == [] and result["skipped"][0]["reason"] == "no preview uploaded"


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({"task_ids": ["t-sh010-anim", "t-hero-mod"]}, "Task t-hero-mod is not a shot of Demo Short"),
        ({"entity_ids": ["s-1", "a-hero"]}, "Entity a-hero is not a shot of Demo Short"),
        ({"task_ids": ["t-nope"]}, "Not found"),
        ({"entity_ids": ["SH010 please"]}, "is not an entity ID"),
        ({}, "Nothing to add"),
        ({"entity_ids": ["s-1"] * 51}, "At most 50"),
    ],
)
async def test_add_to_playlist_checks_everything_before_writing(call, wra, writable, args, error):
    with pytest.raises(ToolError, match=re.escape(error)):
        await call("add_to_playlist", playlist_id="pl-shots", **args)
    assert writes(wra) == []


async def test_add_to_playlist_rejects_entities_of_another_project(call, wra, writable):
    wra.data["shots"].append({**wra.data["shots"][0], "id": "s-other", "name": "SH900", "project_id": "p-2"})
    with pytest.raises(ToolError, match="Entity s-other is not a shot of Demo Short"):
        await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-other"])
    assert writes(wra) == []


async def test_add_to_playlist_reports_success_when_the_reload_fails(call, wra, writable, monkeypatch):
    from kitsu_mcp.tools import write

    monkeypatch.setattr(write, "playlist_detail", lambda raw: (_ for _ in ()).throw(ToolError("Kitsu is down")))
    result = await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-1"])
    assert result["ok"] and "Could not reload the playlist: Kitsu is down" in result["message"]
    assert len(result["added"]) == 1 and result["playlist"] is None
