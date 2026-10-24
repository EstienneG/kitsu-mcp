"""Read tools against a real Zou, seeded by seed.py. Skipped unless KITSU_TEST_HOST is set.

    docker run -d -p 8090:80 cgwire/cgwire:<tag>
    python tests/integration/seed.py http://127.0.0.1:8090/api
    KITSU_TEST_HOST=http://127.0.0.1:8090/api uv run pytest tests/integration

Writes are blocked: these tests only check that the server reads what this Zou version returns.
"""

import json
import os

import pytest
from fastmcp import Client

from kitsu_mcp import client as client_module
from kitsu_mcp import config
from kitsu_mcp import lookups as lookups_module
from kitsu_mcp.client import KitsuClient
from kitsu_mcp.lookups import Lookups

HOST = os.environ.get("KITSU_TEST_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="KITSU_TEST_HOST not set (needs a seeded Zou)")
PROJECT = "MCP Test"


@pytest.fixture(scope="module")
def live_client():
    settings = config.Settings(host=HOST, user="admin@example.com", password="mysecretpassword")  # type: ignore[arg-type]
    kitsu = KitsuClient(settings)

    def blocked(*args, **kwargs):
        raise AssertionError("integration tests must not write to Kitsu")

    kitsu.post = blocked  # type: ignore[method-assign]
    kitsu.put = blocked  # type: ignore[method-assign]
    client_module.set_client(kitsu)
    lookups_module.set_lookups(Lookups(kitsu, ttl=300))
    yield kitsu
    client_module.set_client(None)
    lookups_module.set_lookups(None)


@pytest.fixture
async def call(live_client):
    from kitsu_mcp.server import mcp

    async with Client(mcp) as mcp_client:

        async def _call(name: str, /, **args):
            result = await mcp_client.call_tool(name, args)
            content = result.structured_content
            if content is not None:
                return content["result"] if set(content) == {"result"} else content
            return json.loads(result.content[0].text)

        yield _call


async def test_server_and_reference_data(call):
    assert (await call("whoami"))["email"] == "admin@example.com"
    assert PROJECT in [p["name"] for p in await call("list_projects")]
    assert {"Modeling", "Animation"} <= {t["name"] for t in await call("list_task_types")}
    roles = {s["short_name"].lower(): s["role"] for s in (await call("list_task_statuses"))["statuses"]}
    assert (roles["done"], roles["wip"], roles["todo"]) == ("done", "wip", "todo")
    assert "Character" in {t["name"] for t in await call("list_asset_types", project=PROJECT)}
    assert "admin@example.com" in str(await call("list_people", include_email=True))


async def test_production_views(call):
    overview = await call("project_overview", project=PROJECT)
    assert (overview["assets"], overview["shots"], overview["tasks"]) == (1, 1, 2)
    assert [a["name"] for a in (await call("list_assets", project=PROJECT))["assets"]] == ["Hero"]
    assert [e["name"] for e in await call("list_episodes", project=PROJECT)] == ["E01"]
    assert [s["name"] for s in await call("list_sequences", project=PROJECT)] == ["SQ01"]
    shots = (await call("list_shots", project=PROJECT))["shots"]
    assert [s["name"] for s in shots] == ["SH010"]
    shot = await call("get_shot", shot_id=shots[0]["id"])
    assert shot["name"] == "SH010" and shot["url"]
    casting = await call("get_casting", shot_id=shots[0]["id"])
    assert "Hero" in str(casting)
    await call("list_custom_fields", project=PROJECT)
    await call("recent_previews", project=PROJECT)
    await call("list_playlists", project=PROJECT)


async def test_tasks_and_people(call):
    tasks = (await call("search_tasks", project=PROJECT))["tasks"]
    assert len(tasks) == 2
    anim = next(t for t in tasks if t["task_type"] == "Animation")
    task = await call("get_task", task_id=anim["id"])
    assert "splines" in str(task["comments"])
    assert await call("task_history", task_id=anim["id"])
    assert len(await call("my_tasks")) == 2
    assert (await call("get_person_tasks", person="admin@example.com"))["total"] == 2
    assert await call("workload", project=PROJECT)
