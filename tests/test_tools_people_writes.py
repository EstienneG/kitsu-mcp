"""People and studio write tools against the fake Kitsu, which does what Zou 1.0.97 did on a throwaway instance:
the people listing omits departments unless relations are asked for, a playlist PUT replaces its whole entry
list, inviting sends an email, and Zou takes time logged only by someone assigned to the task."""

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import writes


@pytest.fixture
def admin(fake):
    fake.data["people"][0]["role"] = "admin"  # Alice, the logged-in user


async def test_list_people_shows_departments(call, fake):
    """Zou leaves departments out of its people listing unless asked for relations: released 0.4.0 showed
    every department list empty on a real Kitsu."""
    fake.data["people"][1]["departments"] = ["dep-anim"]
    bob = next(p for p in (await call("list_people"))["people"] if p["full_name"] == "Bob Leroy")
    assert bob["departments"] == ["Animation"]


async def test_create_update_departments_deactivate(call, fake, writable, admin):
    created = await call(
        "manage_person",
        action="create",
        first_name="Cleo",
        last_name="Smith",
        email="cleo@example.com",
        position="artist",
        department="Animation",
    )
    person = next(p for p in fake.data["people"] if p["id"] == created["id"])
    assert person["departments"] == ["dep-anim"] and person["role"] == "user"
    with pytest.raises(ToolError, match="already uses"):
        await call("manage_person", action="create", first_name="X", last_name="Y", email="CLEO@example.com")
    await call("manage_person", action="update", person="Cleo Smith", position="lead")
    assert person["position"] == "lead" and person["first_name"] == "Cleo"
    await call("manage_person", action="add_department", person="Cleo Smith", department="Compositing")
    assert person["departments"] == ["dep-anim", "dep-comp"]
    with pytest.raises(ToolError, match="already in"):
        await call("manage_person", action="add_department", person="Cleo Smith", department="Compositing")
    await call("manage_person", action="remove_department", person="Cleo Smith", department="Animation")
    assert person["departments"] == ["dep-comp"]
    await call("manage_person", action="deactivate", person="Cleo Smith")
    assert person["active"] is False
    with pytest.raises(ToolError, match="already inactive"):
        await call("manage_person", action="deactivate", person="Cleo Smith")


async def test_invite_emails_and_says_so(call, fake, writable, admin):
    plan = await call("manage_person", action="invite", person="Bob Leroy", dry_run=True)
    assert any("real email" in w for w in plan["warnings"]) and "invited" not in fake.data
    await call("manage_person", action="invite", person="Bob Leroy")
    assert fake.data["invited"] == ["person-bob"]


async def test_accounts_are_for_admins(call, fake, writable):
    plan = await call("manage_person", action="update", person="Bob Leroy", position="lead", dry_run=True)
    assert plan["verdict"] == "would_fail" and "only admins" in plan["reason"]


async def test_days_off(call, fake, writable):
    created = await call(
        "manage_day_off", action="add", person="Bob Leroy", start="2026-12-24", end="2026-12-26", description="Xmas"
    )
    overlap = await call("manage_day_off", action="add", person="Bob Leroy", start="2026-12-25", dry_run=True)
    assert any("Overlaps 1" in w for w in overlap["warnings"])
    sheet = await call("timesheet", person="Bob Leroy", start="2026-12-20", end="2026-12-31")
    assert [d["description"] for d in sheet["days_off"]] == ["Xmas"]
    await call("manage_day_off", action="update", day_off_id=created["id"], description="Christmas")
    with pytest.raises(ToolError, match="confirm=True"):
        await call("manage_day_off", action="delete", day_off_id=created["id"])
    await call("manage_day_off", action="delete", day_off_id=created["id"], confirm=True)
    with pytest.raises(ToolError, match="start is after end"):
        await call("manage_day_off", action="add", start="2026-12-26", end="2026-12-24")


async def test_playlist_entry_edits_keep_the_other_entries(call, fake, writable):
    playlist = fake.data["playlists"][0]
    playlist["shots"] = [
        {"entity_id": "s-1", "preview_file_id": "pf-sh010"},
        {"entity_id": "s-2", "preview_file_id": None},
    ]
    await call(
        "manage_playlist", playlist_id=playlist["id"], action="set_preview", entity_id="s-2", preview_file_id="pf-hero"
    )
    assert playlist["shots"] == [
        {"entity_id": "s-1", "preview_file_id": "pf-sh010"},
        {"entity_id": "s-2", "preview_file_id": "pf-hero"},
    ]
    await call("manage_playlist", playlist_id=playlist["id"], action="remove_entry", entity_id="s-2")
    assert playlist["shots"] == [{"entity_id": "s-1", "preview_file_id": "pf-sh010"}]  # s-1 kept
    with pytest.raises(ToolError, match="not in"):
        await call("manage_playlist", playlist_id=playlist["id"], action="remove_entry", entity_id="s-2")
    await call("manage_playlist", playlist_id=playlist["id"], action="rename", name="Dailies v2")
    assert playlist["name"] == "Dailies v2" and len(playlist["shots"]) == 1
    await call("manage_playlist", playlist_id=playlist["id"], action="delete", confirm=True)
    assert all(p["id"] != playlist["id"] for p in fake.data["playlists"])


async def test_notifications(call, fake, writable):
    plan = await call("manage_my_notifications", action="mark_all_read", dry_run=True)
    assert plan["after"] == {"unread": 0}
    await call("manage_my_notifications", action="mark_all_read")
    assert all(n["read"] for n in fake.data.get("notifications", []))
    await call("manage_my_notifications", action="subscribe", task_id="t-sh020-anim")
    assert fake.data["subscriptions"] == {"t-sh020-anim"}
    await call("manage_my_notifications", action="unsubscribe", task_id="t-sh020-anim")
    assert fake.data["subscriptions"] == set()


async def test_set_and_delete_time_only_for_assignees(call, fake, writable):
    plan = await call("manage_time", action="set", task_id="t-hero-mod", day="2026-10-12", minutes=300, dry_run=True)
    assert plan["before"] == {"minutes": 240} and plan["after"] == {"minutes": 300}
    await call("manage_time", action="set", task_id="t-hero-mod", day="2026-10-12", minutes=300)
    day = [e for e in fake.data["time_spents"] if e["task_id"] == "t-hero-mod" and e["date"] == "2026-10-12"]
    assert [e["duration"] for e in day] == [300]  # set, not added
    await call("manage_time", action="delete", task_id="t-hero-mod", day="2026-10-12", confirm=True)
    assert not [e for e in fake.data["time_spents"] if e["task_id"] == "t-hero-mod" and e["date"] == "2026-10-12"]
    refused = await call(
        "manage_time", action="set", task_id="t-sh020-anim", day="2026-10-12", minutes=60, dry_run=True
    )
    assert refused["verdict"] == "would_fail" and "assigned" in refused["reason"]
    assert [w for w in writes(fake) if "t-sh020-anim" in w[1]] == []
