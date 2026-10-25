"""Project configuration tools against the fake Kitsu, which reproduces what Zou 1.0.97 did on a throwaway
instance: updating a custom field or a budget line resets whatever the update leaves out, budget lines take
Zou's salary fields (not gazu's name/amount), and schedule rows and milestones are created by admins only."""

import pytest
from fastmcp.exceptions import ToolError

from tests.fake_data import PROJECT, TT_COMP


@pytest.fixture
def admin(fake):
    fake.data["people"][0]["role"] = "admin"  # Alice, the logged-in user


def project(fake) -> dict:
    return next(p for p in fake.data["projects"] if p["id"] == PROJECT)


async def test_team_add_remove_and_skip(call, fake, writable):
    fake_project = project(fake)
    fake_project["team"] = ["person-alice"]
    plan = await call(
        "manage_project_team", project="Demo Short", action="add", people=["Bob Leroy", "Alice Martin"], dry_run=True
    )
    assert len(plan["requests"]) == 1 and "already in the team" in plan["warnings"][0]
    await call("manage_project_team", project="Demo Short", action="add", people=["Bob Leroy"])
    assert fake_project["team"] == ["person-alice", "person-bob"]
    await call("manage_project_team", project="Demo Short", action="remove", people=["bob@example.com"])
    assert fake_project["team"] == ["person-alice"]


async def test_settings_add_and_remove(call, fake, writable):
    fake_project = project(fake)
    fake_project["task_types"] = []
    await call(
        "manage_project_settings", project="Demo Short", action="add", task_types=["Compositing"], task_statuses=["wip"]
    )
    assert fake_project["task_types"] == [TT_COMP] and fake_project["task_statuses"] == ["st-wip"]
    plan = await call("manage_project_settings", project="Demo Short", action="add", task_types=["COMP"], dry_run=True)
    assert plan["requests"] == [] and "already used" in plan["warnings"][0]
    await call("manage_project_settings", project="Demo Short", action="remove", task_types=["Compositing"])
    assert fake_project["task_types"] == []
    with pytest.raises(ToolError, match="Pass task_types"):
        await call("manage_project_settings", project="Demo Short", action="add")


async def test_custom_field_updates_send_the_whole_field(call, fake, writable):
    """Zou resets what an update leaves out: choices alone would turn a list into a string, and a rename would
    empty the choices. The tool sends every attribute, so neither happens."""
    await call(
        "manage_custom_field",
        project="Demo Short",
        action="create",
        name="Difficulty",
        entity_type="Shot",
        data_type="list",
        choices=["easy", "hard"],
    )
    field = next(f for f in fake.data["custom_fields"] if f["name"] == "Difficulty")
    await call(
        "manage_custom_field",
        project="Demo Short",
        action="update",
        name="Difficulty",
        choices=["easy", "medium", "hard"],
    )
    assert (field["data_type"], field["choices"]) == ("list", ["easy", "medium", "hard"])
    await call("manage_custom_field", project="Demo Short", action="update", name="difficulty", new_name="Complexity")
    assert (field["name"], field["data_type"], field["choices"]) == ("Complexity", "list", ["easy", "medium", "hard"])
    plan = await call(
        "manage_custom_field", project="Demo Short", action="update", name="Complexity", choices=["easy"], dry_run=True
    )
    assert any("removed choice" in w for w in plan["warnings"])
    with pytest.raises(ToolError, match="needs choices"):
        await call("manage_custom_field", project="Demo Short", action="update", name="Complexity", choices=[])
    with pytest.raises(ToolError, match="already has a Shot field"):
        await call("manage_custom_field", project="Demo Short", action="create", name="complexity", entity_type="Shot")
    with pytest.raises(ToolError, match="confirm=True"):
        await call("manage_custom_field", project="Demo Short", action="delete", name="Complexity")
    await call("manage_custom_field", project="Demo Short", action="delete", name="Complexity", confirm=True)
    assert all(f["name"] != "Complexity" for f in fake.data["custom_fields"])


async def test_schedule_rows_and_milestones(call, fake, writable, admin):
    await call(
        "manage_schedule",
        project="Demo Short",
        action="set_task_type_dates",
        task_type="Compositing",
        start_date="2026-11-01",
        end_date="2026-12-15",
        man_days=30,
    )
    row = next(i for i in fake.data["schedule_items"] if i.get("task_type_id") == TT_COMP)
    assert (row["start_date"], row["end_date"], row["man_days"]) == ("2026-11-01", "2026-12-15", 30)
    await call(
        "manage_schedule",
        project="Demo Short",
        action="set_task_type_dates",
        task_type="Compositing",
        end_date="2027-01-31",
    )
    assert (row["start_date"], row["end_date"]) == ("2026-11-01", "2027-01-31")  # start kept
    late = await call(
        "manage_schedule",
        project="Demo Short",
        action="set_task_type_dates",
        task_type="Compositing",
        start_date="2027-06-01",
        dry_run=True,
    )
    assert late["verdict"] == "would_fail"
    await call("manage_schedule", project="Demo Short", action="add_milestone", name="Comp lock", date="2026-12-20")
    milestone = next(m for m in fake.data["milestones"] if m["name"] == "Comp lock")
    shown = await call("production_schedule", project="Demo Short")
    assert "Comp lock" in [m["name"] for m in shown["milestones"]]
    await call(
        "manage_schedule", project="Demo Short", action="delete_milestone", milestone_id=milestone["id"], confirm=True
    )
    assert all(m["id"] != milestone["id"] for m in fake.data["milestones"])


async def test_schedule_creation_warns_non_managers(call, fake, writable):
    """Zou lets admins and the production's managers create schedule rows and milestones (older Zou keeps
    schedule rows to admins), so other roles get a warning rather than a refusal."""
    plan = await call(
        "manage_schedule", project="Demo Short", action="add_milestone", name="Lock", date="2026-12-20", dry_run=True
    )
    assert plan["verdict"] == "would_succeed"
    assert any("admins and the production's managers" in w for w in plan["warnings"])


async def test_budget_lines_use_zous_fields_and_update_sends_the_whole_line(call, fake, writable):
    await call("manage_budget", project="Demo Short", action="create", name="v3", currency="eur")
    budget = next(b for b in fake.data["budgets"] if b["name"] == "v3")
    assert budget["currency"] == "EUR"
    await call(
        "manage_budget",
        project="Demo Short",
        action="add_line",
        budget="v3",
        department="Animation",
        start_month="2026-11",
        months=3,
        daily_rate=250,
        person="Bob Leroy",
    )
    line = fake.data["budget_entries"][budget["id"]][0]
    assert (line["start_date"], line["months_duration"], line["person_id"]) == ("2026-11-01", 3, "person-bob")
    totals = await call("budget", project="Demo Short", version="v3")
    assert totals["total"] == 3 * 20 * 250
    plan = await call(
        "manage_budget",
        project="Demo Short",
        action="update_line",
        budget="v3",
        line_id=line["id"],
        months=4,
        dry_run=True,
    )
    sent = plan["requests"][0]["payload"]
    assert sent["months_duration"] == 4 and sent["department_id"] == line["department_id"]  # the whole line
    assert plan["after"] == {"months_duration": 4}
    await call("manage_budget", project="Demo Short", action="update_line", budget="v3", line_id=line["id"], months=4)
    assert (await call("budget", project="Demo Short", version="v3"))["total"] == 4 * 20 * 250
    with pytest.raises(ToolError, match="confirm=True"):
        await call("manage_budget", project="Demo Short", action="delete_line", budget="v3", line_id=line["id"])
    await call("manage_budget", project="Demo Short", action="delete", budget="v3", confirm=True)
    assert all(b["name"] != "v3" for b in fake.data["budgets"])
