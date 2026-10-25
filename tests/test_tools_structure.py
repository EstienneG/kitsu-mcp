"""Structure tools (manage_project, manage_shot, ...) against the fake Kitsu.

The fake follows what a real Zou 1.0.97 does (checked against a throwaway instance): creates append, entity
updates merge custom fields, deleting an entity with tasks cancels it unless forced, only closed projects can be
deleted, and every new TV show gets an episode E01.
"""

import pytest
from fastmcp.exceptions import ToolError

from tests.fake_data import PROJECT, TT_ANIM, TT_MODEL
from tests.test_tools_write import writable, writes  # noqa: F401  (fixture)


@pytest.fixture
def seq(fake):
    return fake.data["sequences"][0]


async def test_create_shot_then_refuse_its_name_again(call, fake, writable, seq):  # noqa: F811
    plan = await call(
        "manage_shot",
        action="create",
        project="Demo Short",
        sequence=seq["name"],
        name="SH099",
        nb_frames=48,
        frame_in=1001,
        dry_run=True,
    )
    assert plan["verdict"] == "would_succeed" and writes(fake) == []
    assert plan["requests"] == [
        {
            "method": "POST",
            "path": f"data/projects/{PROJECT}/shots",
            "payload": {"name": "SH099", "sequence_id": seq["id"], "data": {"frame_in": 1001}, "nb_frames": 48},
        }
    ]
    result = await call(
        "manage_shot",
        action="create",
        project="Demo Short",
        sequence=seq["name"],
        name="SH099",
        nb_frames=48,
        frame_in=1001,
    )
    assert result["ok"] and result["entity"]["name"] == "SH099" and result["id"]
    with pytest.raises(ToolError, match="already has a shot 'SH099'"):
        await call("manage_shot", action="create", project="Demo Short", sequence=seq["name"], name="sh099")


async def test_update_sends_only_changed_custom_fields(call, fake, writable, seq):  # noqa: F811
    shot = (
        await call(
            "manage_shot",
            action="create",
            project="Demo Short",
            sequence=seq["name"],
            name="SH100",
            frame_in=1,
            custom_fields={"note": "x"},
        )
    )["id"]
    plan = await call("manage_shot", action="update", shot_id=shot, frame_in=1, frame_out=24, dry_run=True)
    assert plan["after"] == {"data": {"frame_out": 24}} and plan["before"] == {"data": {"frame_out": None}}
    await call("manage_shot", action="update", shot_id=shot, frame_in=1, frame_out=24)
    record = next(s for s in fake.data["shots"] if s["id"] == shot)
    assert record["data"] == {"frame_in": 1, "note": "x", "frame_out": 24}  # merged, nothing lost
    same = await call("manage_shot", action="update", shot_id=shot, frame_out=24, dry_run=True)
    assert same["requests"] == [] and "no request" in same["warnings"][0]
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("manage_shot", action="update", shot_id=shot)


async def test_delete_needs_confirm_and_cancels_a_shot_with_tasks(call, fake, writable):  # noqa: F811
    shot = fake.data["shots"][0]  # has tasks in the seed
    with pytest.raises(ToolError, match="confirm=True"):
        await call("manage_shot", action="delete", shot_id=shot["id"])
    assert writes(fake) == []
    plan = await call("manage_shot", action="delete", shot_id=shot["id"], dry_run=True)
    assert plan["would"].startswith("Cancel") and plan["after"] == {"exists": True, "canceled": True}
    await call("manage_shot", action="delete", shot_id=shot["id"], confirm=True)
    assert shot["canceled"] is True and any(t["entity_id"] == shot["id"] for t in fake.data["tasks"])
    await call("manage_shot", action="restore", shot_id=shot["id"])
    assert shot["canceled"] is False
    with pytest.raises(ToolError, match="not canceled"):
        await call("manage_shot", action="restore", shot_id=shot["id"])
    forced = await call("manage_shot", action="delete", shot_id=shot["id"], force=True, confirm=True, dry_run=True)
    assert forced["would"].startswith("Delete") and "also deletes" in forced["warnings"][0]
    await call("manage_shot", action="delete", shot_id=shot["id"], force=True, confirm=True)
    assert all(s["id"] != shot["id"] for s in fake.data["shots"])
    assert all(t["entity_id"] != shot["id"] for t in fake.data["tasks"])


async def test_assets_create_update_delete(call, fake, writable):  # noqa: F811
    created = await call("manage_asset", action="create", project="Demo Short", asset_type="Character", name="Villain")
    assert created["ok"] and created["url"]
    with pytest.raises(ToolError, match="already has a Character 'Villain'"):
        await call("manage_asset", action="create", project="Demo Short", asset_type="Character", name="villain")
    await call("manage_asset", action="update", asset_id=created["id"], description="Bad guy")
    assert next(a for a in fake.data["assets"] if a["id"] == created["id"])["description"] == "Bad guy"
    gone = await call("manage_asset", action="delete", asset_id=created["id"], confirm=True)  # no tasks: deleted
    assert gone["ok"] and gone["id"] is None
    assert all(a["id"] != created["id"] for a in fake.data["assets"])


async def test_tasks_create_skips_existing_and_delete(call, fake, writable):  # noqa: F811
    shots = [s["id"] for s in fake.data["shots"]]
    before = len(fake.data["tasks"])
    plan = await call("manage_task", action="create", entity_ids=shots + shots[:1], task_type="Animation", dry_run=True)
    already = {t["entity_id"] for t in fake.data["tasks"] if t["task_type_id"] == TT_ANIM}
    assert len(plan["requests"]) == len(set(shots) - already)
    assert len([w for w in plan["warnings"] if w.startswith("Skipped")]) == len(set(shots) & already)
    await call(
        "manage_task", action="create", entity_ids=shots, task_type="Animation", status="wip", assignees=["Bob Leroy"]
    )
    assert len(fake.data["tasks"]) == before + len(set(shots) - already)
    again = await call("manage_task", action="create", entity_ids=shots, task_type="Animation", dry_run=True)
    assert again["requests"] == [] and any("Nothing to create" in w for w in again["warnings"])
    task = next(t for t in fake.data["tasks"] if t["task_type_id"] == TT_MODEL)
    with pytest.raises(ToolError, match="confirm=True"):
        await call("manage_task", action="delete", task_id=task["id"])
    await call("manage_task", action="delete", task_id=task["id"], confirm=True)
    assert all(t["id"] != task["id"] for t in fake.data["tasks"])


async def test_sequences_episodes_concepts_edits(call, fake, writable):  # noqa: F811
    sequence = await call("manage_sequence", action="create", project="Demo Short", name="SQ900")
    assert sequence["ok"]
    with pytest.raises(ToolError, match="already has a sequence"):
        await call("manage_sequence", action="create", project="Demo Short", name="sq900")
    renamed = await call("manage_sequence", action="update", sequence_id=sequence["id"], name="SQ901")
    assert renamed["ok"]
    plan = await call("manage_sequence", action="delete", sequence_id=sequence["id"], confirm=True, dry_run=True)
    assert "refuses if the sequence still holds anything" in plan["warnings"][0]
    await call("manage_sequence", action="delete", sequence_id=sequence["id"], confirm=True)
    concept = await call("manage_concept", action="create", project="Demo Short", name="Hero v3")
    with pytest.raises(ToolError, match="already has a concept"):
        await call("manage_concept", action="create", project="Demo Short", name="hero v3")
    edit = await call("manage_edit", action="create", project="Demo Short", name="Teaser")
    for tool, key, record in (("manage_concept", "concept_id", concept), ("manage_edit", "edit_id", edit)):
        assert (await call(tool, action="delete", confirm=True, **{key: record["id"]}))["ok"]


async def test_tv_show_episodes_and_project_lifecycle(call, fake, writable):  # noqa: F811
    created = await call("manage_project", action="create", name="New Show", production_type="tvshow", fps=25)
    assert created["ok"] and "E01" in created["message"]
    assert created["entity"]["name"] == "New Show"
    with pytest.raises(ToolError, match="already has an episode 'E01'"):  # Kitsu made it
        await call("manage_episode", action="create", project="New Show", name="E01")
    assert (await call("manage_episode", action="create", project="New Show", name="E02"))["ok"]
    seq = await call("manage_sequence", action="create", project="New Show", name="SQ01", episode="E02")
    assert next(s for s in fake.data["sequences"] if s["id"] == seq["id"])["parent_id"]
    with pytest.raises(ToolError, match="A project named 'New Show' already exists"):
        await call("manage_project", action="create", name="new show")
    update = await call("manage_project", action="update", project="New Show", description="Pilot season", dry_run=True)
    assert update["requests"][0]["path"] == f"data/projects/{created['id']}"
    blocked = await call("manage_project", action="delete", project="New Show", confirm=True, dry_run=True)
    assert blocked["verdict"] == "would_fail" and "close" in blocked["reason"]
    with pytest.raises(ToolError, match="only deletes closed projects.*Nothing was sent"):  # refused before sending
        await call("manage_project", action="delete", project="New Show", confirm=True)
    await call("manage_project", action="close", project="New Show")
    with pytest.raises(ToolError, match="already closed"):
        await call("manage_project", action="close", project="New Show")
    assert (await call("manage_project", action="delete", project="New Show", confirm=True))["ok"]
    assert all(p["name"] != "New Show" for p in fake.data["projects"])


async def test_structure_tools_need_writes_and_sit_in_their_group(call, fake):
    from fastmcp import Client

    from kitsu_mcp.server import mcp

    async with Client(mcp) as client:
        listed = (await client.call_tool("load_tools", {"groups": ["structure"]})).data
    assert "write tools need KITSU_ALLOW_WRITE" in listed  # nothing is enabled without writes
    with pytest.raises(ToolError, match="Unknown tool"):
        await call("manage_shot", action="create", project="Demo Short", sequence="SQ010", name="X")
