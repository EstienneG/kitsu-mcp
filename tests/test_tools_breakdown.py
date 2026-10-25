"""Breakdown tools against the fake Kitsu, which does what Zou 1.0.97 did on a throwaway instance: the casting
route replaces the whole casting, sequence casting is {shot id: [assets]}, scene asset instances come as
{asset id: [instances]}, and Zou's forced project delete fails while scenes hold asset instances."""

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import writes


def cast(fake, shot_id: str) -> dict[str, int]:
    return {c["asset_name"]: c["nb_occurences"] for c in fake.data["casting"].get(shot_id, [])}


async def test_add_and_remove_keep_the_rest_of_the_casting(call, fake, writable):
    assert cast(fake, "s-1") == {"Hero": 1}
    plan = await call(
        "set_casting", entity_id="s-1", action="add", assets=["Forest"], occurrences={"Forest": 2}, dry_run=True
    )
    assert plan["before"] == {"casting": {"Hero": 1}} and plan["after"] == {"casting": {"Hero": 1, "Forest": 2}}
    assert writes(fake) == []
    await call("set_casting", entity_id="s-1", action="add", assets=["Forest"], occurrences={"Forest": 2})
    assert cast(fake, "s-1") == {"Hero": 1, "Forest": 2}  # Hero kept although Zou replaces the whole list
    sent = [c for c in writes(fake) if c[0] == "PUT"][-1][2]
    assert {c["asset_id"] for c in sent} == {"a-hero", "a-forest"}
    await call("set_casting", entity_id="s-1", action="remove", assets=["Hero"])
    assert cast(fake, "s-1") == {"Forest": 2}
    plan = await call("set_casting", entity_id="s-1", action="remove", assets=["Hero"], dry_run=True)
    assert plan["requests"] == [] and any("Not cast already: Hero" in w for w in plan["warnings"])


async def test_replace_warns_about_what_it_uncasts(call, fake, writable):
    await call("set_casting", entity_id="s-1", action="add", assets=["Forest"])
    plan = await call("set_casting", entity_id="s-1", action="replace", assets=["Forest"], dry_run=True)
    assert any("replace uncasts 1 asset(s) not in the list: Hero" in w for w in plan["warnings"])
    with pytest.raises(ToolError, match="No asset 'Nobody'"):
        await call("set_casting", entity_id="s-1", action="add", assets=["Nobody"])
    with pytest.raises(ToolError, match="1 or more"):
        await call("set_casting", entity_id="s-1", action="add", assets=["Hero"], occurrences={"Hero": 0})


async def test_get_casting_every_way_round(call, fake, writable):
    await call("set_casting", entity_id="s-2", action="add", assets=["Hero", "Forest"])
    by_sequence = await call("get_casting", sequence_id=fake.data["shots"][0]["parent_id"])
    assert {s["shot"]: {a["name"] for a in s["assets"]} for s in by_sequence} == {
        "SH010": {"Hero"},
        "SH020": {"Forest", "Hero"},
    }
    assert {a["name"] for a in await call("get_casting", shot_id="s-2")} == {"Hero", "Forest"}
    with pytest.raises(ToolError, match="exactly one"):
        await call("get_casting", shot_id="s-1", asset_id="a-hero")


async def test_scenes(call, fake, writable):
    sequence = fake.data["sequences"][0]
    scene = await call("manage_scene", action="create", project="Demo Short", sequence=sequence["name"], name="SC01")
    with pytest.raises(ToolError, match="already has a scene"):
        await call("manage_scene", action="create", project="Demo Short", sequence=sequence["name"], name="sc01")
    await call("manage_scene", action="add_shot", scene_id=scene["id"], shot_id="s-1")
    with pytest.raises(ToolError, match="already in"):
        await call("manage_scene", action="add_shot", scene_id=scene["id"], shot_id="s-1")
    await call("manage_scene", action="add_asset", scene_id=scene["id"], asset_id="a-hero")
    assert [i["asset_id"] for i in fake.data["asset_instances"]] == ["a-hero"]
    await call("manage_scene", action="remove_shot", scene_id=scene["id"], shot_id="s-1")
    with pytest.raises(ToolError, match="is not in"):
        await call("manage_scene", action="remove_shot", scene_id=scene["id"], shot_id="s-1")


async def test_project_delete_clears_scene_instances_first(call, fake, writable):
    """Zou's forced project delete fails while scenes hold asset instances: the tool removes them first."""
    created = await call("manage_project", action="create", name="Scene Show")
    project_id = created["id"]
    await call("manage_sequence", action="create", project="Scene Show", name="SQ01")
    asset = await call("manage_asset", action="create", project="Scene Show", asset_type="Character", name="Hero")
    scene = await call("manage_scene", action="create", project="Scene Show", sequence="SQ01", name="SC01")
    await call("manage_scene", action="add_asset", scene_id=scene["id"], asset_id=asset["id"])
    await call("manage_project", action="close", project="Scene Show")
    plan = await call("manage_project", action="delete", project="Scene Show", force=True, confirm=True, dry_run=True)
    assert [r["path"].split("/")[1] for r in plan["requests"]] == ["asset-instances", "projects"]
    fake.data["me"] = "person-bob"  # a supervisor, not an admin: the instance route is admins-only
    refused = await call(
        "manage_project", action="delete", project="Scene Show", force=True, confirm=True, dry_run=True
    )
    assert refused["verdict"] == "would_fail" and "only an admin" in refused["reason"]
    fake.data["me"] = "person-alice"
    fake.data["people"][0]["role"] = "admin"
    await call("manage_project", action="delete", project="Scene Show", force=True, confirm=True)
    assert all(p["id"] != project_id for p in fake.data["projects"])


async def test_casting_edits_keep_labels(call, fake, writable):
    """Zou rebuilds the whole casting and gives a link not sent with a label an empty one."""
    assert fake.data["casting"]["s-1"][0]["label"] == "animate"
    await call("set_casting", entity_id="s-1", action="add", assets=["Forest"])
    hero = next(c for c in fake.data["casting"]["s-1"] if c["asset_id"] == "a-hero")
    assert hero["label"] == "animate"


async def test_casting_refuses_when_canceled_assets_would_be_dropped(call, fake, writable):
    """Zou's casting read hides canceled assets, but its PUT deletes their links: refuse instead of dropping."""
    shot = next(s for s in fake.data["shots"] if s["id"] == "s-1")
    shot["entities_out"] = ["a-hero", "a-canceled"]  # a-canceled is cast but hidden from the read
    plan = await call("set_casting", entity_id="s-1", action="add", assets=["Forest"], dry_run=True)
    assert plan["verdict"] == "would_fail" and "canceled asset" in plan["reason"]
    with pytest.raises(ToolError, match="drop them for good"):
        await call("set_casting", entity_id="s-1", action="add", assets=["Forest"])
    assert writes(fake) == []


async def test_removing_from_an_episode_lists_the_shots_it_uncasts(call, fake, writable):
    """Zou removes an asset that leaves an episode's casting from that episode's shots too."""
    episode = {"id": "ep-1", "name": "E01", "project_id": "p-1", "type": "Episode"}
    fake.data["episodes"].append(episode)
    sequence = fake.data["sequences"][0]
    sequence["parent_id"] = "ep-1"
    fake.data["casting"]["ep-1"] = [{"asset_id": "a-hero", "asset_name": "Hero", "nb_occurences": 1, "label": ""}]
    plan = await call("set_casting", entity_id="ep-1", action="remove", assets=["Hero"], dry_run=True)
    assert any("also uncasts Hero from" in w and "SH010" in w for w in plan["warnings"])
    await call("set_casting", entity_id="ep-1", action="remove", assets=["Hero"])
    assert fake.data["casting"]["s-1"] == []  # what the warning said
