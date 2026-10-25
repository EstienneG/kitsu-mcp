import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import ALICE


async def test_project_activity_lists_changes_newest_first(call):
    result = await call("project_activity", project="Demo Short", since="2026-08-01")
    dates = [i["date"] for i in result["items"]]
    assert dates == sorted(dates, reverse=True) and len(dates) == result["total"]
    first = result["items"][0]
    assert (first["entity"], first["task_type"], first["author"]) == ("Hero", "Modeling", "Alice Martin")
    assert first["comment_id"] == "c-2" and first["preview_file_id"] == "pf-hero"
    assert sum(result["authors"].values()) == len(result["items"])


async def test_project_activity_defaults_to_the_last_two_days(call, fake):
    fake.data["comments"]["t-hero-mod"][0]["created_at"] = "2026-10-14T18:00:00"  # today is 2026-10-15
    result = await call("project_activity", project="p-1")
    assert [i["comment_id"] for i in result["items"]] == ["c-2"]
    feed_params = [params for _, path, params in fake.calls if path == "data/projects/p-1/news"]
    assert feed_params[0]["after"] == "2026-10-13"


async def test_project_activity_filters(call):
    bob = await call("project_activity", project="p-1", since="2026-08-01", person="Bob Leroy")
    assert bob["items"] and {i["author"] for i in bob["items"]} == {"Bob Leroy"}
    anim = await call("project_activity", project="p-1", since="2026-08-01", task_type="ANIM", limit=2)
    assert len(anim["items"]) == 2 and {i["task_type"] for i in anim["items"]} == {"Animation"}
    named = await call("project_activity", project="p-1", since="2026-08-01", entity_name_contains="hero")
    assert {i["entity"] for i in named["items"]} == {"Hero"}


async def test_project_activity_status_changes_only(call, fake):
    fake.data["comments"]["t-hero-mod"][1]["change"] = False
    result = await call("project_activity", project="p-1", since="2026-08-01", status_changes_only=True)
    assert "c-1" not in [i["comment_id"] for i in result["items"]]
    assert all(i["status_changed"] for i in result["items"])


async def test_my_notifications_unread_first(call):
    result = await call("my_notifications")
    assert (result["total"], result["unread"]) == (1, 1)
    note = result["notifications"][0]
    assert (note["type"], note["author"], note["status"]) == ("comment", "Bob Leroy", "retake")
    assert note["text"] == "Edges flicker, please fix" and note["task_type"] == "Compositing"
    everything = await call("my_notifications", unread_only=False)
    assert [n["read"] for n in everything["notifications"]] == [False, True]
    assert (await call("my_notifications", unread_only=False, project="Closed Show"))["total"] == 0


async def test_search_across_kinds(call):
    result = await call("search", query="hero")
    assert {(h["kind"], h["name"]) for h in result["hits"]} == {("asset", "Hero"), ("concept", "Hero sketch v2")}
    assert result["hits"][0]["name"] == "Hero"  # exact match first
    assert result["hits"][0]["detail"] == "Character"
    shots = await call("search", query="sh0", kinds=["shot"], project="Demo Short")
    assert {h["name"] for h in shots["hits"]} == {"SQ010 / SH010", "SQ010 / SH020"}
    assert {h["detail"] for h in shots["hits"]} == {"SQ010"}
    assert [h["kind"] for h in (await call("search", query="trailer"))["hits"]] == ["edit"]
    assert [h["name"] for h in (await call("search", query="bob", kinds=["person"]))["hits"]] == ["Bob Leroy"]


async def test_search_rejects_bad_input(call):
    with pytest.raises(ToolError, match="empty"):
        await call("search", query="  ")
    with pytest.raises(ToolError, match="Unknown kinds"):
        await call("search", query="x", kinds=["planet"])


async def test_timesheet_defaults_to_me_and_last_week(call):
    sheet = await call("timesheet")
    assert (sheet["person"], sheet["start"], sheet["end"]) == ("Alice Martin", "2026-10-09", "2026-10-15")
    assert sheet["total_minutes"] == 480
    assert sheet["by_day"] == [{"date": "2026-10-12", "minutes": 240}, {"date": "2026-10-13", "minutes": 240}]
    assert [(t["entity"], t["minutes"]) for t in sheet["by_task"]] == [("Hero", 420), ("SH010", 60)]


async def test_timesheet_for_someone_and_a_range(call):
    sheet = await call("timesheet", person="Bob Leroy", start="2026-10-01", end="2026-10-31")
    assert (sheet["total_minutes"], sheet["by_task"][0]["entity"]) == (120, "Forest")
    september = await call("timesheet", person=ALICE, start="2026-09-01", end="2026-09-30")
    assert september["total_minutes"] == 500
    with pytest.raises(ToolError, match="after end"):
        await call("timesheet", start="2026-10-10", end="2026-10-01")


async def test_timesheet_shows_days_off_overlapping_the_period(call):
    sheet = await call("timesheet")  # 2026-10-09 .. 2026-10-15
    assert sheet["days_off"] == [{"start": "2026-10-09", "end": "2026-10-12", "description": "Trip"}]
    assert (await call("timesheet", person="Bob Leroy"))["days_off"] == []
    august = await call("timesheet", start="2026-08-10", end="2026-08-20")
    assert [d["start"] for d in august["days_off"]] == ["2026-08-03"]
