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
