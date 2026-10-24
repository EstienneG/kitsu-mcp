"""Output-shape features: compact lists, grouping, feedback filter, dates, emails, skip counts."""


async def test_list_shots_and_assets_compact(call):
    shots = await call("list_shots", project="p-1")
    first = shots["shots"][0]
    assert first["tasks"] is None and first["statuses"] == {"Animation": "done", "Compositing": "retake"}
    assets = await call("list_assets", project="p-1", asset_types=["Character"])
    assert assets["assets"][0]["statuses"] == {"Modeling": "wfa"} and assets["assets"][0]["tasks"] is None


async def test_search_waiting_feedback(call):
    result = await call("search_tasks", project="p-1", waiting_feedback=True)
    assert [t["id"] for t in result["tasks"]] == ["t-hero-mod"]


async def test_search_group_by_assignee(call):
    result = await call("search_tasks", project="p-1", include_done=False, group_by="assignee")
    assert result["tasks"] == [] and result["total"] == 4
    groups = {g["assignee"]: g for g in result["by_assignee"]}
    assert groups["Bob Leroy"]["count"] == 2 and groups["Bob Leroy"]["overdue"] == 1
    assert groups["Alice Martin"]["tasks"] == ["Hero / Modeling (wfa, due 2026-10-01)"]
    assert groups["(unassigned)"]["count"] == 1
    # Busiest first.
    assert result["by_assignee"][0]["assignee"] == "Bob Leroy"


async def test_task_dates_are_days_and_tasks_carry_ids(call, fake):
    next(t for t in fake.data["tasks"] if t["id"] == "t-hero-mod")["due_date"] = "2026-10-01T00:00:00"
    task = await call("get_task", task_id="t-hero-mod", include_comments=False)
    assert task["due_date"] == "2026-10-01" and task["entity_id"] == "a-hero"
    asset = await call("get_asset", asset_id="a-hero")
    assert asset["tasks"][0]["due_date"] == "2026-10-01"
    assert "last_preview_file_id" in asset["tasks"][0]


async def test_list_people_hides_emails_by_default(call):
    assert all(p["email"] is None for p in await call("list_people"))
    assert {p["email"] for p in await call("list_people", include_email=True)} == {
        "alice@example.com",
        "bob@example.com",
    }


async def test_get_person_tasks_limit(call):
    assert len(await call("get_person_tasks", person="Bob Leroy", limit=1)) == 1


async def test_download_previews_reports_why_entities_were_skipped(call, fake, tmp_path):
    fake.data["assets"].append({**fake.data["assets"][0], "id": "a-cut", "name": "Cut", "canceled": True})
    (tmp_path / "SH010_s-1.png").write_bytes(b"mine")
    result = await call("download_previews", project="p-1", dest_dir=str(tmp_path), size="thumbnail")
    assert (result["no_preview"], result["canceled"], result["already_downloaded"]) == (2, 1, 1)
    assert result["skipped"] == 4 and [s["id"] for s in result["saved"]] == ["a-hero"]
