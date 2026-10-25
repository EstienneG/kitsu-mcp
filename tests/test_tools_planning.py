import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import BOB, PROJECT, TT_ANIM


async def test_quotas_per_person_with_unpadded_weeks_in_order(call, fake):
    result = await call("quotas", project="Demo Short", task_type="Animation")
    assert (result["task_type"], result["period"], result["count_mode"]) == ("Animation", "week", "done")
    [alice] = result["people"]  # Bob delivered nothing: left out
    assert alice["person"] == "Alice Martin"
    assert (alice["total_shots"], alice["total_frames"], alice["total_seconds"]) == (3.0, 96, 4.0)
    assert list(alice["shots"]) == ["2026-7", "2026-40"]  # week 7 before week 40, empty weeks dropped
    assert ("GET", f"data/projects/{PROJECT}/quotas/{TT_ANIM}", {"count_mode": "done"}) in fake.calls


async def test_quotas_since_and_month(call):
    recent = await call("quotas", project="Demo Short", task_type="ANIM", since="2026-09-28")
    assert recent["people"][0]["shots"] == {"2026-40": 2.0}  # 2026-09-28 is in ISO week 40
    months = await call("quotas", project="Demo Short", task_type="Animation", period="month", since="2026-03-01")
    assert months["people"][0]["shots"] == {"2026-10": 2.0}
    assert (await call("quotas", project="Demo Short", task_type="Animation", person=BOB))["people"] == []


async def test_quotas_reject_unknown_modes(call):
    with pytest.raises(ToolError):
        await call("quotas", project="Demo Short", task_type="Animation", count_mode="weigtheddone")


async def test_production_schedule(call):
    schedule = await call("production_schedule", project="Demo Short")
    assert (schedule["start"], schedule["end"]) == ("2026-01-01", "2026-12-31")
    spans = {s["task_type"]: s for s in schedule["task_types"]}
    assert list(spans) == ["Modeling", "Animation"]  # by planned start
    assert spans["Modeling"]["late"] and spans["Modeling"]["man_days"] == 40
    assert spans["Modeling"]["open_tasks"] >= 1
    assert not spans["Animation"]["late"]
    assert schedule["late"] == ["Modeling"]
    assert [m["name"] for m in schedule["milestones"]] == ["Anim lock", "Delivery"]
    assert schedule["milestones"][0]["task_type"] == "Animation"
    only_anim = await call("production_schedule", project="Demo Short", task_types=["Modeling"])
    assert [s["task_type"] for s in only_anim["task_types"]] == ["Modeling"]
    assert [m["name"] for m in only_anim["milestones"]] == ["Delivery"]  # project-wide milestones stay


async def test_budget_follows_kitsus_month_costs(call):
    result = await call("budget", project="Demo Short")
    assert (result["name"], result["revision"], result["currency"]) == ("Revised", 2, "EUR")
    lines = {line["person"]: line for line in result["lines"]}
    # Sept and Nov at 100 x 20 days, October set by hand to 500; the exception outside the span is ignored.
    assert lines["Alice Martin"]["cost"] == 2000 + 500 + 2000
    assert lines["Bob Leroy"]["cost"] == 4000
    assert result["total"] == 8500
    assert result["by_department"] == {"Animation": 4500, "Modeling": 4000}
    first = await call("budget", project="Demo Short", budget="first pass")
    assert first["revision"] == 1 and first["total"] == 0
    with pytest.raises(ToolError, match="Revised"):
        await call("budget", project="Demo Short", budget="Final")
    with pytest.raises(ToolError, match="no budget"):
        await call("budget", project="Closed Show")


async def test_planning_tools_are_in_the_planning_group(call):
    from fastmcp import Client

    from kitsu_mcp.server import mcp

    async with Client(mcp) as client:
        result = (await client.call_tool("load_tools", {"groups": ["planning"]})).data
    for name in ("quotas", "production_schedule", "budget", "workload", "timesheet"):
        assert name in result
