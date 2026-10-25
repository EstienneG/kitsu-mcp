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

from kitsu_mcp import config
from kitsu_mcp.kitsu import client as client_module
from kitsu_mcp.kitsu import lookups as lookups_module
from kitsu_mcp.kitsu.client import KitsuClient
from kitsu_mcp.kitsu.lookups import Lookups

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
    assert (await call("get_task", task_id=anim["id"], include_history=True))["history"]
    assert (await call("get_person_tasks"))["total"] == 2
    assert (await call("get_person_tasks", person="admin@example.com"))["total"] == 2
    assert await call("workload", project=PROJECT)


async def test_activity_search_and_timesheet(call):
    activity = await call("project_activity", project=PROJECT, since="2020-01-01")
    assert any("splines" in str(i) or i["task_type"] == "Animation" for i in activity["items"])
    assert "Super Admin" in activity["authors"]
    assert (await call("my_notifications", unread_only=False))["total"] >= 0
    hits = await call("search", query="sh01", project=PROJECT)
    assert ("shot", "SQ01 / SH010") in {(h["kind"], h["name"]) for h in hits["hits"]}
    assert ("asset", "Hero") in {(h["kind"], h["name"]) for h in (await call("search", query="hero"))["hits"]}
    sheet = await call("timesheet", start="2020-01-01", end="2030-12-31")
    assert sheet["person"] == "Super Admin" and sheet["total_minutes"] >= 0


async def test_planning_views(call, live_client):
    """Shapes these Zou versions return for quotas, schedule, budgets and days off; and that reading the
    schedule creates nothing (Kitsu's own schedule route adds missing items as it reads)."""
    project_id = next(p["id"] for p in await call("list_projects") if p["name"] == PROJECT)
    before = live_client.get(f"data/projects/{project_id}/schedule-items")
    schedule = await call("production_schedule", project=PROJECT)
    assert live_client.get(f"data/projects/{project_id}/schedule-items") == before
    assert schedule["project"] == PROJECT and isinstance(schedule["unscheduled"], list)
    for mode in ("done", "feedback", "weighted", "weighteddone"):
        quotas = await call("quotas", project=PROJECT, task_type="Animation", count_mode=mode)
        assert "total" not in {p["person"] for p in quotas["people"]}
    with pytest.raises(Exception, match="no budget"):
        await call("budget", project=PROJECT)
    assert (await call("timesheet", start="2020-01-01", end="2030-12-31"))["days_off"] == []


async def test_planning_views_as_a_producer(live_client):
    """Producers (Kitsu role manager) are who these views are for: they must not need admin-only routes."""
    from kitsu_mcp.server import mcp
    from tests.integration.seed import PRODUCER

    settings = config.Settings(host=HOST, user=PRODUCER[0], password=PRODUCER[1])  # type: ignore[arg-type]
    producer = KitsuClient(settings)
    producer.post = live_client.post  # type: ignore[method-assign]  (blocked)
    producer.put = live_client.put  # type: ignore[method-assign]
    client_module.set_client(producer)
    lookups_module.set_lookups(Lookups(producer, ttl=300))
    try:
        async with Client(mcp) as session:
            assert (await session.call_tool("whoami", {})).data["role"] == "manager"
            schedule = await session.call_tool("production_schedule", {"project": PROJECT})
            assert schedule.structured_content["result"]["project"] == PROJECT
            await session.call_tool("quotas", {"project": PROJECT, "task_type": "Animation"})
            # Days off may be hidden from a producer while time logs are not; Zou 1.0.43 hides both.
            try:
                sheet = (await session.call_tool("timesheet", {"person": "Super Admin"})).data
            except Exception as error:
                assert "time-spents" in str(error), error
            else:
                assert sheet["person"] == "Super Admin"
    finally:
        client_module.set_client(live_client)
        lookups_module.set_lookups(Lookups(live_client, ttl=300))
