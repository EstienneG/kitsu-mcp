import re

import pytest
from fastmcp.exceptions import ToolError

from kitsu_mcp.server import mcp
from tests.fakes import ALICE, BOB, ST_DONE, ST_WFA, TT_ANIM

WRITE_TOOLS = {
    "add_comment",
    "acknowledge_comment",
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
                "is_for_all": False,
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
        ({"episode": "EP01"}, "Demo Short has no episodes"),
    ],
)
async def test_create_playlist_rejects_bad_arguments_before_writing(call, fake, writable, args, error):
    with pytest.raises(ToolError, match=re.escape(error)):
        await call("create_playlist", **{"project": "p-1", "name": "New", "for_entity": "shot", **args})
    assert writes(fake) == []


@pytest.fixture
def show(fake):
    """Closed Show (p-2) with episodes EP01 and EP02, a shot in each, and an EP01 'Dailies' playlist."""
    fake.data["episodes"] = [
        {"id": "ep-1", "name": "EP01", "project_id": "p-2"},
        {"id": "ep-2", "name": "EP02", "project_id": "p-2"},
    ]
    shot = fake.data["shots"][0]
    for n, episode in ((1, "ep-1"), (2, "ep-2")):
        fake.data["sequences"].append(
            {"id": f"seq-e{n}", "name": f"SQ0{n}", "project_id": "p-2", "parent_id": episode, "type": "Sequence"}
        )
        fake.data["shots"].append(
            {**shot, "id": f"s-e{n}", "name": f"E{n}_SH010", "project_id": "p-2", "parent_id": f"seq-e{n}"}
        )
    fake.data["playlists"].append(
        {**fake.data["playlists"][0], "id": "pl-ep1", "project_id": "p-2", "episode_id": "ep-1", "shots": []}
    )
    return fake


async def test_create_playlist_in_a_tv_show_needs_the_episode(call, show, writable):
    with pytest.raises(ToolError, match="pass the episode"):
        await call("create_playlist", project="Closed Show", name="New", for_entity="shot")
    with pytest.raises(ToolError, match="Unknown episode 'EP03'"):
        await call("create_playlist", project="Closed Show", name="New", for_entity="shot", episode="EP03")
    assert writes(show) == []
    await call("create_playlist", project="Closed Show", name="New", for_entity="shot", episode="ep01")
    assert writes(show)[0][2]["episode_id"] == "ep-1"


async def test_tv_show_without_episodes_needs_no_episode(call, fake, writable):
    """Some TV shows (Wing It) have no episodes: their shot playlists are project-level."""
    await call("create_playlist", project="Closed Show", name="New", for_entity="shot")
    assert "episode_id" not in writes(fake)[0][2]


async def test_playlist_names_are_unique_per_episode(call, show, writable):
    with pytest.raises(ToolError, match=re.escape("named 'Dailies' in this episode (ID pl-ep1)")):
        await call("create_playlist", project="p-2", name="dailies ", for_entity="shot", episode="EP01")
    assert writes(show) == []
    await call("create_playlist", project="p-2", name="Dailies", for_entity="shot", episode="EP02")
    assert writes(show)[0][2]["episode_id"] == "ep-2"


async def test_add_to_episode_playlist_rejects_shots_of_other_episodes(call, show, writable):
    with pytest.raises(ToolError, match=re.escape("s-e2 (E2_SH010) is not in the episode of playlist 'Dailies'")):
        await call("add_to_playlist", playlist_id="pl-ep1", entity_ids=["s-e1", "s-e2"])
    assert writes(show) == []
    result = await call("add_to_playlist", playlist_id="pl-ep1", entity_ids=["s-e1"])
    assert [e["entity"] for e in result["added"]] == ["E1_SH010"]


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
        ({"task_ids": ["t-sh010-anim"], "task_type": "Animation"}, "task_type picks the preview of entity_ids"),
        ({"entity_ids": ["s-1"], "task_type": "Lighting"}, "Unknown task type 'Lighting'"),
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


async def test_add_entity_with_a_broken_current_preview_is_skipped(call, wra, writable):
    wra.data["shots"][0]["preview_file_id"] = "pf-sh010-broken"
    result = await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-1"])
    assert adds(wra) == []
    assert "current preview is broken" in result["skipped"][0]["reason"]


async def test_add_entities_with_the_latest_preview_of_a_task_type(call, wra, writable):
    # SH010's current preview is set by hand to revision 1; task_type picks the Animation task's latest.
    wra.data["shots"][0]["preview_file_id"] = "pf-sh010-v1"
    result = await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-1", "s-2"], task_type="anim")
    assert adds(wra) == [{"entity_id": "s-1", "preview_file_id": "pf-sh010"}]
    assert [(e["task_type"], e["revision"]) for e in result["added"]] == [("Animation", 2)]
    assert result["skipped"] == [{"ref": "s-2", "entity": "SH020", "reason": "no anim preview uploaded"}]


async def test_task_type_with_several_tasks_takes_the_most_recent_upload(call, wra, writable):
    wra.data["tasks"].append({**wra.data["tasks"][2], "id": "t-sh010-anim2"})
    wra.data["preview_files"]["pf-anim2"] = {
        **wra.data["preview_files"]["pf-sh010"],
        "id": "pf-anim2",
        "task_id": "t-sh010-anim2",
        "revision": 1,
        "created_at": "2026-10-01T10:00:00",
    }
    result = await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-1"], task_type="Animation")
    assert [(e["preview_file_id"], e["revision"]) for e in result["added"]] == [("pf-anim2", 1)]


async def test_task_type_the_entity_lacks_is_skipped(call, wra, writable):
    result = await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-2"], task_type="Compositing")
    assert result["skipped"][0]["reason"] == "no Compositing task" and adds(wra) == []


async def test_add_to_playlist_takes_exactly_50_and_dedupes_within_a_call(call, wra, writable):
    result = await call(
        "add_to_playlist", playlist_id="pl-shots", entity_ids=["s-1"] * 25, task_ids=["t-sh010-anim"] * 25
    )
    assert len(adds(wra)) == 1
    assert len(result["added"]) == 1 and len(result["skipped"]) == 49
    assert {s["reason"] for s in result["skipped"]} == {"already in the playlist"}


async def test_failure_mid_add_reports_progress_and_a_retry_finishes(call, wra, writable, monkeypatch):
    post = wra.post

    def flaky(path, data):
        if data.get("entity_id") == "a-forest":
            raise ToolError("POST failed: timed out; it MAY have been applied.")
        return post(path, data)

    wra.data["assets"][1]["preview_file_id"] = "pf-hero"
    monkeypatch.setattr(wra, "post", flaky)
    with pytest.raises(ToolError) as error:
        await call("add_to_playlist", playlist_id="pl-assets", entity_ids=["a-hero", "a-forest"])
    assert "Added Hero before failing on Forest: POST failed: timed out; it MAY have been applied. Calling" in str(
        error.value
    )
    monkeypatch.setattr(wra, "post", post)
    retry = await call("add_to_playlist", playlist_id="pl-assets", entity_ids=["a-hero", "a-forest"])
    assert [e["entity"] for e in retry["added"]] == ["Forest"]
    assert retry["skipped"] == [{"ref": "a-hero", "entity": "Hero", "reason": "already in the playlist"}]


async def test_failure_mid_add_keeps_the_progress_report_for_any_error(call, wra, writable, monkeypatch):
    def broken(path, data):
        raise ConnectionResetError("connection reset")

    monkeypatch.setattr(wra, "post", broken)
    with pytest.raises(ToolError, match="Added nothing before failing on SH010: connection reset. Calling"):
        await call("add_to_playlist", playlist_id="pl-shots", entity_ids=["s-1"])


# --- dry_run -------------------------------------------------------------------------------------------------

# One real-looking call per write tool: (tool, arguments, expected before, expected after).
DRY_RUNS = [
    (
        "add_comment",
        {"task_id": "t-hero-mod", "text": "Approved", "status": "done"},
        {"status": "wfa"},
        {"status": "done"},
    ),
    ("set_task_status", {"task_id": "t-hero-mod", "status": "retake"}, {"status": "wfa"}, {"status": "retake"}),
    (
        "assign_task",
        {"task_id": "t-hero-mod", "person": "bob"},
        {"assignees": ["Alice Martin"]},
        {"assignees": ["Alice Martin", "Bob Leroy"]},
    ),
    (
        "update_task_schedule",
        {"task_id": "t-hero-mod", "due_date": "2026-11-01", "estimation_minutes": 120},
        {"due_date": "2026-10-01", "estimation": 960},
        {"due_date": "2026-11-01", "estimation": 120},
    ),
    (
        "log_time",
        {"task_id": "t-hero-mod", "minutes": 90, "day": "2026-10-14"},
        {"task_total": 600, "person_day": 0},
        {"task_total": 690, "person_day": 90},
    ),
    (
        "add_comment",
        {"task_id": "t-hero-mod", "reply_to": "c-2", "text": "Looks good"},
        {"replies": 0},
        {"replies": 1},
    ),
    (
        "acknowledge_comment",
        {"task_id": "t-hero-mod", "comment_id": "c-2"},
        {"acknowledged": False},
        {"acknowledged": True},
    ),
]


@pytest.mark.parametrize("name, args, before, after", DRY_RUNS, ids=[d[0] for d in DRY_RUNS])
async def test_dry_run_writes_nothing_and_plans_the_real_call(call, fake, writable, name, args, before, after):
    plan = await call(name, **args, dry_run=True)
    assert writes(fake) == [], "a dry run must not POST or PUT"
    assert (plan["dry_run"], plan["ok"], plan["verdict"]) == (True, True, "would_succeed")
    assert plan["would"] and plan["reason"] is None
    assert (plan["before"], plan["after"]) == (before, after)

    result = await call(name, **args)
    assert result["ok"] is True and "dry_run" not in result
    assert [(r["method"], r["path"], r["payload"]) for r in plan["requests"]] == writes(fake)


async def test_dry_run_shows_the_one_line_action(call, fake, writable):
    plan = await call("set_task_status", task_id="t-sh010-comp", status="wip", dry_run=True)
    assert plan["would"] == "Change SH010 / Compositing from retake to wip"


async def test_dry_run_warns_without_failing(call, fake, writable):
    plan = await call("set_task_status", task_id="t-hero-mod", status="wfa", dry_run=True)
    assert plan["verdict"] == "would_succeed"
    assert any("already wfa" in w for w in plan["warnings"])
    plan = await call("assign_task", task_id="t-hero-mod", person="alice", dry_run=True)
    assert plan["before"] == plan["after"] and any("already assigned" in w for w in plan["warnings"])


async def test_dry_run_warns_when_kitsu_may_refuse_the_role(call, fake, writable):
    """Alice is an artist ("user"); done is not open to artists and assigning is for leads."""
    plan = await call("set_task_status", task_id="t-hero-mod", status="done", dry_run=True)
    assert plan["verdict"] == "would_succeed"
    assert any("not open to artists" in w for w in plan["warnings"])
    assert any("closes the task" in w for w in plan["warnings"])
    plan = await call("assign_task", task_id="t-sh020-anim", person="bob", dry_run=True)
    assert any("usually cannot assign" in w for w in plan["warnings"])


def _archive_done(fake):
    next(s for s in fake.data["statuses"] if s["id"] == ST_DONE)["archived"] = True


def _deactivate_bob(fake):
    next(p for p in fake.data["people"] if p["id"] == BOB)["active"] = False


def _full_day(fake):
    fake.data["time_spents"] = [{"task_id": "t-hero-mod", "person_id": ALICE, "date": "2026-10-14", "duration": 1400}]


FAILING = [
    ("add_comment", {"task_id": "t-hero-mod", "text": "ok", "status": "done"}, _archive_done, "archived"),
    ("set_task_status", {"task_id": "t-hero-mod", "status": "done"}, _archive_done, "archived"),
    ("assign_task", {"task_id": "t-sh020-anim", "person": "bob"}, _deactivate_bob, "inactive"),
    ("update_task_schedule", {"task_id": "t-hero-mod", "start_date": "2026-10-05"}, lambda fake: None, "after the due"),
    ("log_time", {"task_id": "t-hero-mod", "minutes": 60, "day": "2026-10-14"}, _full_day, "over 24 h"),
]


@pytest.mark.parametrize("name, args, setup, reason", FAILING, ids=[f[0] for f in FAILING])
async def test_failing_check_is_a_verdict_in_dry_run_and_an_error_for_real(
    call, fake, writable, name, args, setup, reason
):
    setup(fake)
    plan = await call(name, **args, dry_run=True)
    assert (plan["ok"], plan["verdict"]) == (False, "would_fail")
    assert reason in plan["reason"]
    assert plan["requests"], "the plan still shows what would have been sent"
    with pytest.raises(ToolError, match=reason):
        await call(name, **args)
    assert writes(fake) == []


@pytest.mark.parametrize(
    "name, args, error",
    [
        ("set_task_status", {"task_id": "t-hero-mod", "status": "approvedd"}, "Unknown task status"),
        ("assign_task", {"task_id": "t-hero-mod", "person": "nobody"}, "Unknown person"),
        ("update_task_schedule", {"task_id": "t-hero-mod"}, "Nothing to update"),
        ("log_time", {"task_id": "t-hero-mod", "minutes": 0}, "between 1 and 1440"),
        ("add_comment", {"task_id": "not an id", "text": "hi"}, "not a task ID"),
    ],
)
async def test_dry_run_still_raises_on_bad_arguments(call, fake, writable, name, args, error):
    with pytest.raises(ToolError, match=error):
        await call(name, **args, dry_run=True)
    assert writes(fake) == []


async def test_log_time_dry_run_counts_the_persons_day(call, fake, writable):
    fake.data["time_spents"] = [{"task_id": "t-hero-mod", "person_id": BOB, "date": "2026-10-14", "duration": 30}]
    plan = await call("log_time", task_id="t-hero-mod", minutes=60, day="2026-10-14", person="bob", dry_run=True)
    assert plan["before"]["person_day"] == 30 and plan["after"]["person_day"] == 90
    assert plan["requests"][0]["path"] == f"actions/tasks/t-hero-mod/time-spents/2026-10-14/persons/{BOB}/add"


async def test_dry_run_log_appends_jsonl(call, fake, writable, tmp_path, monkeypatch):
    import json

    log = tmp_path / "plans.jsonl"
    monkeypatch.setattr(fake.settings, "dry_run_log", log)
    await call("assign_task", task_id="t-sh020-anim", person="bob", dry_run=True)
    await call("log_time", task_id="t-hero-mod", minutes=5, dry_run=True)
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [line["tool"] for line in lines] == ["assign_task", "log_time"]
    assert lines[0]["requests"][0]["method"] == "PUT" and lines[0]["dry_run"] is True
    await call("assign_task", task_id="t-sh020-anim", person="bob")
    assert len(log.read_text().splitlines()) == 2, "real calls are not logged"


async def test_every_write_tool_has_dry_run(writable):
    """Any tool tagged write (not just the ones listed here) must offer dry_run, documented."""
    tagged = {t.name: t for t in await mcp.list_tools() if "write" in (t.tags or set())}
    assert set(tagged) == WRITE_TOOLS, "WRITE_TOOLS is out of date"
    for name, t in tagged.items():
        assert t.parameters["properties"]["dry_run"]["default"] is False, name
        assert "dry_run=True" in (t.description or ""), name


async def test_create_playlist_dry_run_writes_nothing_and_plans_the_real_call(call, fake, writable):
    args = {"project": "p-1", "name": "WRA shots", "for_entity": "shot", "task_type": "anim"}
    plan = await call("create_playlist", **args, dry_run=True)
    assert writes(fake) == [] and (plan["dry_run"], plan["verdict"]) == (True, "would_succeed")
    planned = [(r["method"], r["path"], r["payload"]) for r in plan["requests"]]
    await call("create_playlist", **args)
    assert writes(fake) == planned


async def test_add_to_playlist_dry_run_lists_adds_and_skips_without_writing(call, fake, writable):
    playlist = (await call("create_playlist", project="p-1", name="Review", for_entity="shot"))["playlist"]
    fake.calls.clear()
    args = {"playlist_id": playlist["id"], "task_ids": ["t-sh010-anim", "t-sh020-anim"]}
    plan = await call("add_to_playlist", **args, dry_run=True)
    assert writes(fake) == []
    assert [r["payload"]["entity_id"] for r in plan["requests"]] == ["s-1"]
    assert any("SH020" in w for w in plan["warnings"])  # no preview uploaded: skipped
    planned = [(r["method"], r["path"], r["payload"]) for r in plan["requests"]]
    await call("add_to_playlist", **args)
    assert writes(fake) == planned


def test_plan_send_reports_partial_progress(fake):
    from kitsu_mcp.plans import PartialSendError, Plan

    plan = Plan("test", would="two comments")
    plan.request("POST", "actions/tasks/t-hero-mod/comment", {"task_status_id": ST_WFA, "comment": "one"})
    plan.request("POST", "actions/tasks/t-missing/comment", {"task_status_id": ST_WFA, "comment": "two"})
    with pytest.raises(PartialSendError, match="Sent 1 of 2 requests, then failed") as raised:
        plan.send()
    assert raised.value.sent == 1
    assert len(writes(fake)) == 2


def test_plan_with_failed_check_sends_nothing(fake):
    from kitsu_mcp.plans import Plan

    plan = Plan("test", would="a comment")
    plan.request("POST", "actions/tasks/t-hero-mod/comment", {"task_status_id": ST_WFA, "comment": "one"})
    plan.fail("Not allowed.")
    with pytest.raises(ToolError, match="Not allowed. Nothing was sent."):
        plan.send()
    assert writes(fake) == []


# --- replies and acknowledgements ------------------------------------------------------------------------------


async def test_reply_to_comment(call, fake, writable):
    result = await call("add_comment", task_id="t-hero-mod", reply_to="c-2", text="Looks good")
    assert result["ok"] and result["message"] == "Reply posted."
    assert writes(fake) == [("POST", "data/tasks/t-hero-mod/comments/c-2/reply", {"text": "Looks good"})]
    task = await call("get_task", task_id="t-hero-mod", comment_limit=1)
    assert task["comments"][0]["replies"][0]["text"] == "Looks good"
    assert task["status"] == "wfa"  # a reply leaves the status alone


async def test_reply_checks_the_comment_belongs_to_the_task(call, fake, writable):
    with pytest.raises(ToolError, match="not on task"):
        await call("add_comment", task_id="t-sh010-anim", reply_to="c-2", text="Hi")
    with pytest.raises(ToolError, match="empty"):
        await call("add_comment", task_id="t-hero-mod", reply_to="c-2", text=" ")
    with pytest.raises(ToolError, match="cannot change the status"):
        await call("add_comment", task_id="t-hero-mod", reply_to="c-2", text="Hi", status="done")
    assert writes(fake) == []


async def test_acknowledge_comment_never_toggles_it_back(call, fake, writable):
    """Zou's ack route toggles: a second call must not send it again (that would un-acknowledge)."""
    first = await call("acknowledge_comment", task_id="t-hero-mod", comment_id="c-2")
    assert first["message"] == "Comment acknowledged."
    again = await call("acknowledge_comment", task_id="t-hero-mod", comment_id="c-2")
    assert again["message"] == "Already acknowledged; nothing changed."
    assert len(writes(fake)) == 1
    task = await call("get_task", task_id="t-hero-mod", comment_limit=1)
    assert task["comments"][0]["acknowledged_by"] == ["Alice Martin"]
    plan = await call("acknowledge_comment", task_id="t-hero-mod", comment_id="c-2", dry_run=True)
    assert plan["requests"] == [] and plan["before"] == {"acknowledged": True}
