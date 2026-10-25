"""Department filters: a task is in a department when its task type is."""

import pytest
from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.lookups import Lookups
from tests.fake_data import TT_ANIM, TT_COMP
from tests.fakes import FakeClient


def test_department_lookup_resolves_names_and_ids():
    lookups = Lookups(FakeClient(), ttl=300)  # type: ignore[arg-type]
    assert lookups.department("animation")["id"] == "dep-anim"
    assert lookups.department("dep-comp")["name"] == "Compositing"
    assert lookups.department_task_types(["ANIMATION", "dep-comp"]) == {TT_ANIM, TT_COMP}
    assert lookups.department_task_types(None) is None
    assert lookups.department_task_types(["Sound"]) == set()  # a department without task types matches nothing
    with pytest.raises(ToolError, match="Unknown department 'Anim'.*Did you mean: Animation"):
        lookups.department("Anim")


async def test_search_tasks_by_department(call):
    result = await call("search_tasks", project="p-1", departments=["Animation"])
    assert sorted(t["id"] for t in result["tasks"]) == ["t-sh010-anim", "t-sh020-anim"]
    result = await call("search_tasks", project="p-1", departments=["animation", "Compositing"], include_done=False)
    assert sorted(t["id"] for t in result["tasks"]) == ["t-sh010-comp", "t-sh020-anim"]
    # Combined with task_types, both must match.
    result = await call("search_tasks", project="p-1", departments=["Animation"], task_types=["Compositing"])
    assert result["total"] == 0


async def test_workload_by_department(call):
    rows = await call("workload", project="p-1", departments=["Modeling"])
    assert {r["person"]: r["open_tasks"] for r in rows} == {"Alice Martin": 1, "Bob Leroy": 1}
    rows = await call("workload", project="p-1", departments=["dep-comp"])
    assert [(r["person"], r["open_tasks"], r["overdue"], r["retakes"]) for r in rows] == [("Bob Leroy", 1, 1, 1)]


@pytest.mark.parametrize("tool", ["search_tasks", "workload", "project_overview"])
async def test_unknown_department_is_an_error(call, tool):
    with pytest.raises(ToolError, match="Unknown department 'Animaton'.*Did you mean: Animation"):
        await call(tool, project="p-1", departments=["Animaton"])


@pytest.mark.parametrize("departments", [["Animation"], ["Modeling"], ["Compositing", "Animation"], ["Sound"]])
async def test_search_workload_and_overview_agree_under_a_department_filter(call, departments):
    overview = await call("project_overview", project="p-1", departments=departments)
    open_tasks = await call("search_tasks", project="p-1", departments=departments, include_done=False)
    overdue = await call("search_tasks", project="p-1", departments=departments, overdue=True)
    every = await call("search_tasks", project="p-1", departments=departments, include_omitted=True)
    rows = await call("workload", project="p-1", departments=departments)
    assert overview["tasks"] == every["total"]
    assert overview["overdue"] == overdue["total"] == sum(r["overdue"] for r in rows)
    # Workload counts a task once per assignee; with one assignee per task here the totals match.
    assert open_tasks["total"] == sum(r["open_tasks"] for r in rows)
    assert overview["unassigned_open"] == sum(r["open_tasks"] for r in rows if r["person"] == "(unassigned)")


async def test_list_people_names_departments_from_the_cache(call, fake):
    fake.data["people"][0]["departments"] = ["dep-anim", "dep-gone"]
    people = await call("list_people", project="p-1")
    assert people["people"][0]["departments"] == ["Animation", "dep-gone"]
    await call("list_people")
    await call("search_tasks", project="p-1", departments=["Animation"])
    assert sum(path == "data/departments" for _, path, _ in fake.calls) == 1
