"""Write tools against a throwaway Zou: what they send must work on real Zou versions.

Writes for real, so it needs both KITSU_TEST_HOST and KITSU_TEST_WRITES=1, and refuses any host but the local
test container. Never point it at a Kitsu you care about. Everything it creates lives in its own project, which
it deletes at the end.

    docker run -d -p 8090:80 cgwire/cgwire:<tag>
    KITSU_TEST_HOST=http://127.0.0.1:8090/api KITSU_TEST_WRITES=1 uv run pytest tests/integration
"""

import os
from urllib.parse import urlsplit

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from kitsu_mcp import config
from kitsu_mcp.kitsu import client as client_module
from kitsu_mcp.kitsu import lookups as lookups_module
from kitsu_mcp.kitsu.client import KitsuClient
from kitsu_mcp.kitsu.lookups import Lookups

HOST = os.environ.get("KITSU_TEST_HOST")
WRITES = os.environ.get("KITSU_TEST_WRITES") == "1"
pytestmark = pytest.mark.skipif(not (HOST and WRITES), reason="needs KITSU_TEST_HOST and KITSU_TEST_WRITES=1")
PROJECT = "MCP Write Test"


@pytest.fixture(scope="module")
def kitsu():
    if urlsplit(HOST or "").hostname not in ("127.0.0.1", "localhost"):
        pytest.fail("write tests only run against a local throwaway Zou (127.0.0.1 or localhost)")
    settings = config.Settings(host=HOST, user="admin@example.com", password="mysecretpassword")  # type: ignore[arg-type]
    real = KitsuClient(settings)
    client_module.set_client(real)
    lookups_module.set_lookups(Lookups(real, ttl=0))  # see each write's effect at once
    yield real
    client_module.set_client(None)
    lookups_module.set_lookups(None)


@pytest.fixture
async def call(kitsu):
    from kitsu_mcp.server import groups, mcp

    mcp.enable(tags={"write"})
    groups.set_default_groups("all")
    async with Client(mcp) as session:

        async def _call(tool_name: str, /, **args):
            result = await session.call_tool(tool_name, args)
            content = result.structured_content or {}
            return content["result"] if set(content) == {"result"} else content

        yield _call
    mcp.disable(tags={"write"})
    groups.set_default_groups("write")


async def test_structure_lifecycle(call, kitsu):
    """A TV show from creation to deletion, through every structure tool, as Zou really behaves."""
    project = await call("manage_project", action="create", name=PROJECT, production_type="tvshow", fps=24)
    assert project["ok"] and "E01" in project["message"]  # Zou adds E01 to every TV show
    try:
        with pytest.raises(ToolError, match="already has an episode 'E01'"):
            await call("manage_episode", action="create", project=PROJECT, name="E01")
        sequence = await call("manage_sequence", action="create", project=PROJECT, name="SQ01", episode="E01")
        shot = await call(
            "manage_shot",
            action="create",
            project=PROJECT,
            sequence="SQ01",
            episode="E01",
            name="SH010",
            nb_frames=48,
            frame_in=1001,
        )
        assert shot["entity"]["nb_frames"] == 48 and shot["entity"]["parent_id"] == sequence["id"]
        await call("manage_shot", action="update", shot_id=shot["id"], frame_out=1048)
        assert kitsu.get(f"data/shots/{shot['id']}")["data"] == {"frame_in": 1001, "frame_out": 1048}

        created = await call("manage_task", action="create", entity_ids=[shot["id"]], task_type="Animation")
        assert created["ok"] and len(kitsu.get(f"data/shots/{shot['id']}/tasks")) == 1
        again = await call("manage_task", action="create", entity_ids=[shot["id"]], task_type="Animation", dry_run=True)
        assert again["requests"] == []  # already there

        await call("manage_shot", action="delete", shot_id=shot["id"], confirm=True)  # has a task: canceled
        assert kitsu.get(f"data/shots/{shot['id']}")["canceled"] is True
        await call("manage_shot", action="restore", shot_id=shot["id"])
        assert kitsu.get(f"data/shots/{shot['id']}")["canceled"] is False
        await call("manage_shot", action="delete", shot_id=shot["id"], force=True, confirm=True)
        assert kitsu.get(f"data/sequences/{sequence['id']}")  # the sequence is still there

        asset_type = kitsu.get("data/asset-types")[0]["name"]
        asset = await call("manage_asset", action="create", project=PROJECT, asset_type=asset_type, name="Hero")
        await call("manage_asset", action="update", asset_id=asset["id"], description="The hero")
        assert kitsu.get(f"data/assets/{asset['id']}")["description"] == "The hero"
        concept = await call("manage_concept", action="create", project=PROJECT, name="Hero sketch")
        edit = await call("manage_edit", action="create", project=PROJECT, name="Animatic", episode="E01")
        for tool, key, record in (
            ("manage_asset", "asset_id", asset),
            ("manage_concept", "concept_id", concept),
            ("manage_edit", "edit_id", edit),
            ("manage_sequence", "sequence_id", sequence),
        ):
            assert (await call(tool, action="delete", confirm=True, **{key: record["id"]}))["ok"]

        blocked = await call("manage_project", action="delete", project=PROJECT, confirm=True, dry_run=True)
        assert blocked["verdict"] == "would_fail"  # Zou only deletes closed projects
    finally:
        await call("manage_project", action="close", project=PROJECT)
        await call("manage_project", action="delete", project=PROJECT, force=True, confirm=True)
    assert PROJECT not in [p["name"] for p in kitsu.get("data/projects")]


async def test_task_lifecycle(call, kitsu, tmp_path):
    """Start, submit, publish a real file, act in batch, edit and delete comments, on real Zou."""
    from PIL import Image

    name = f"{PROJECT} lifecycle"
    await call("manage_project", action="create", name=name)
    try:
        await call("manage_sequence", action="create", project=name, name="SQ01")
        shots = [
            (await call("manage_shot", action="create", project=name, sequence="SQ01", name=f"SH0{i}0"))["id"]
            for i in (1, 2, 3)
        ]
        await call("manage_task", action="create", entity_ids=shots, task_type="Animation")
        tasks = [kitsu.get(f"data/shots/{s}/tasks")[0]["id"] for s in shots]

        def status(task_id: str) -> str:
            return kitsu.get(f"data/tasks/{task_id}/full")["task_status"]["short_name"].lower()

        await call("task_action", action="start", task_id=tasks[0])
        assert status(tasks[0]) == "wip"
        await call("task_action", action="submit_for_review", task_id=tasks[0])
        assert status(tasks[0]) == "wfa"

        frame = tmp_path / "frame.png"
        Image.new("RGB", (64, 36), (200, 80, 40)).save(frame)
        published = await call("publish_preview", task_id=tasks[0], file_path=str(frame), comment="v1", set_main=True)
        previews = kitsu.get(f"data/tasks/{tasks[0]}/previews")
        assert published["ok"] and [p["revision"] for p in previews] == [1]
        assert kitsu.get(f"data/entities/{shots[0]}")["preview_file_id"] == previews[0]["id"]

        await call("batch_tasks", action="status", task_ids=tasks, status="wip")
        assert all(status(t) == "wip" for t in tasks)
        await call("batch_tasks", action="assign", task_ids=tasks, person="admin@example.com")
        me = kitsu.user_id()
        assert all(me in kitsu.get(f"data/tasks/{t}")["assignees"] for t in tasks)
        await call("batch_tasks", action="unassign", task_ids=tasks)
        await call("batch_tasks", action="priority", task_ids=tasks, priority=2)
        assert all(kitsu.get(f"data/tasks/{t}")["priority"] == 2 for t in tasks)

        comment = next(c for c in kitsu.get(f"data/tasks/{tasks[0]}/comments") if c.get("previews"))
        await call("manage_comment", action="edit", task_id=tasks[0], comment_id=comment["id"], text="v1 fixed")
        await call("manage_comment", action="delete", task_id=tasks[0], comment_id=comment["id"], confirm=True)
        assert kitsu.get(f"data/tasks/{tasks[0]}/previews") == []  # Zou deletes a comment's previews with it

        deleted = await call("batch_tasks", action="delete", task_ids=tasks[1:], confirm=True)
        assert deleted["ok"] and all(kitsu.get(f"data/shots/{s}/tasks") == [] for s in shots[1:])
    finally:
        await call("manage_project", action="close", project=name)
        await call("manage_project", action="delete", project=name, force=True, confirm=True)


async def test_breakdown(call, kitsu):
    """Casting add/remove keep the rest (Zou replaces the whole list), sequence casting, scenes; and deleting a
    project whose scenes hold asset instances, which Zou's own forced delete fails on."""
    name = f"{PROJECT} breakdown"
    await call("manage_project", action="create", name=name)
    try:
        asset_type = kitsu.get("data/asset-types")[0]["name"]
        hero = await call("manage_asset", action="create", project=name, asset_type=asset_type, name="Hero")
        await call("manage_asset", action="create", project=name, asset_type=asset_type, name="Sword")
        sequence = await call("manage_sequence", action="create", project=name, name="SQ01")
        shot = await call("manage_shot", action="create", project=name, sequence="SQ01", name="SH010")

        def cast() -> dict:
            route = f"data/projects/{shot['entity']['project_id']}/entities/{shot['id']}/casting"
            return {c["asset_name"]: c["nb_occurences"] for c in kitsu.get(route)}

        await call("set_casting", entity_id=shot["id"], action="add", assets=["Hero"])
        await call("set_casting", entity_id=shot["id"], action="add", assets=["Sword"], occurrences={"Sword": 2})
        assert cast() == {"Hero": 1, "Sword": 2}
        await call("set_casting", entity_id=shot["id"], action="remove", assets=["Hero"])
        assert cast() == {"Sword": 2}
        by_sequence = await call("get_casting", sequence_id=sequence["id"])
        assert [(s["shot"], [a["name"] for a in s["assets"]]) for s in by_sequence] == [("SH010", ["Sword"])]

        scene = await call("manage_scene", action="create", project=name, sequence="SQ01", name="SC01")
        await call("manage_scene", action="add_shot", scene_id=scene["id"], shot_id=shot["id"])
        await call("manage_scene", action="add_asset", scene_id=scene["id"], asset_id=hero["id"])
        assert [s["id"] for s in kitsu.get(f"data/scenes/{scene['id']}/shots")] == [shot["id"]]
    finally:
        await call("manage_project", action="close", project=name)
        await call("manage_project", action="delete", project=name, force=True, confirm=True)
    assert name not in [p["name"] for p in kitsu.get("data/projects")]


async def test_project_configuration(call, kitsu):
    """Team, settings, custom fields (Zou resets what an update leaves out), schedule and milestones (admin
    routes), and budget lines (Zou's salary fields; a partial update would be refused)."""
    name = f"{PROJECT} config"
    created = await call("manage_project", action="create", name=name)
    project_id = created["id"]
    try:
        await call("manage_project_team", project=name, action="add", people=["admin@example.com"])
        assert kitsu.user_id() in kitsu.get(f"data/projects/{project_id}")["team"]
        await call(
            "manage_project_settings", project=name, action="add", task_types=["Animation"], task_statuses=["wip"]
        )
        assert len(kitsu.get(f"data/projects/{project_id}")["task_types"]) == 1

        await call(
            "manage_custom_field",
            project=name,
            action="create",
            name="Difficulty",
            entity_type="Shot",
            data_type="list",
            choices=["easy", "hard"],
        )
        await call(
            "manage_custom_field", project=name, action="update", name="Difficulty", choices=["easy", "medium", "hard"]
        )
        await call("manage_custom_field", project=name, action="update", name="Difficulty", new_name="Complexity")
        field = next(d for d in kitsu.get(f"data/projects/{project_id}/metadata-descriptors"))
        assert (field["name"], field["data_type"], field["choices"]) == (
            "Complexity",
            "list",
            ["easy", "medium", "hard"],
        )

        await call(
            "manage_schedule",
            project=name,
            action="set_task_type_dates",
            task_type="Animation",
            start_date="2026-11-01",
            end_date="2026-12-15",
        )
        await call("manage_schedule", project=name, action="add_milestone", name="Lock", date="2026-12-20")
        assert [m["name"] for m in kitsu.get(f"data/projects/{project_id}/milestones")] == ["Lock"]

        await call("manage_budget", project=name, action="create", name="v1", currency="EUR")
        department = kitsu.get("data/departments")[0]["name"]
        await call(
            "manage_budget",
            project=name,
            action="add_line",
            budget="v1",
            department=department,
            start_month="2026-11",
            months=3,
            daily_rate=250,
        )
        assert (await call("budget", project=name))["total"] == 15000
        budget_id = kitsu.get(f"data/projects/{project_id}/budgets")[0]["id"]
        line = kitsu.get(f"data/projects/{project_id}/budgets/{budget_id}/entries")[0]
        await call("manage_budget", project=name, action="update_line", budget="v1", line_id=line["id"], months=4)
        assert (await call("budget", project=name))["total"] == 20000
    finally:
        await call("manage_project", action="close", project=name)
        await call("manage_project", action="delete", project=name, force=True, confirm=True)
