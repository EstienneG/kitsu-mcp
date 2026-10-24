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
    assert all(p["email"] is None for p in (await call("list_people"))["people"])
    assert {p["email"] for p in (await call("list_people", include_email=True))["people"]} == {
        "alice@example.com",
        "bob@example.com",
    }


async def test_get_person_tasks_limit(call):
    page = await call("get_person_tasks", person="Bob Leroy", limit=1, offset=1)
    assert page["total"] == 2 and [t["id"] for t in page["tasks"]] == ["t-forest-mod"]
    assert set(page["tasks"][0]) == {"id", "project", "entity", "entity_type", "task_type", "status", "due_date"}
    full = await call("get_person_tasks", person="Bob Leroy", detail="full")
    assert "estimation" in full["tasks"][0] and "sequence" in full["tasks"][0]


async def test_download_previews_reports_why_entities_were_skipped(call, fake, tmp_path):
    fake.data["assets"].append({**fake.data["assets"][0], "id": "a-cut", "name": "Cut", "canceled": True})
    (tmp_path / "SH010_s-1.png").write_bytes(b"mine")
    result = await call("download_previews", project="p-1", dest_dir=str(tmp_path), size="thumbnail")
    assert (result["no_preview"], result["canceled"], result["already_downloaded"]) == (2, 1, 1)
    assert result["skipped"] == 4 and [s["id"] for s in result["saved"]] == ["a-hero"]


async def test_group_by_reports_group_count(call):
    result = await call("search_tasks", project="p-1", include_done=False, group_by="assignee", limit=1)
    assert (result["total"], result["groups"], len(result["by_assignee"])) == (4, 3, 1)


async def test_list_task_types_includes_types_used_but_not_declared(call, fake):
    fake.data["projects"][0]["task_types"] = ["tt-model"]  # Animation and Compositing are used, not declared
    assert sorted(t["name"] for t in await call("list_task_types", project="p-1")) == [
        "Animation",
        "Compositing",
        "Modeling",
    ]


async def test_group_by_caps_tasks_per_person(call):
    result = await call("search_tasks", project="p-1", include_done=False, group_by="assignee", tasks_per_group=1)
    bob = next(g for g in result["by_assignee"] if g["assignee"] == "Bob Leroy")
    assert (bob["count"], len(bob["tasks"]), bob["more"], bob["overdue"]) == (2, 1, 1, 1)


async def test_kitsu_get_caps_list_answers(call, fake):
    fake.data["people"] += [{**fake.data["people"][0], "id": f"p{i}", "full_name": f"P{i}"} for i in range(300)]
    result = await call("kitsu_get", path="data/persons", max_items=10)
    assert result["truncated"] is True and (result["total"], result["returned"]) == (302, 10)
    assert len(result["items"]) == 10
    small = await call("kitsu_get", path="data/task-types")
    assert isinstance(small, list) and len(small) == 4  # small answers come back unchanged


async def test_kitsu_get_caps_answer_size(call, fake):
    fake.data["people"] = [{**fake.data["people"][0], "id": f"p{i}", "bio": "x" * 2000} for i in range(60)]
    result = await call("kitsu_get", path="data/persons", max_items=60)
    assert result["truncated"] is True and result["returned"] < 60
    assert len(str(result["items"])) < 60_000


async def test_kitsu_get_bounds_lists_inside_dicts(call, fake, monkeypatch):
    feed = {"data": [{"id": f"n{i}", "text": "x" * 200} for i in range(500)], "total": 500}
    monkeypatch.setattr(fake, "_route", lambda path, params: feed)
    result = await call("kitsu_get", path="data/projects/p-1/news", max_items=20)
    assert result["total"] == 500
    assert result["data"]["truncated"] is True and result["data"]["returned"] == 20


async def test_kitsu_get_never_returns_a_huge_single_item(call, fake, monkeypatch):
    monkeypatch.setattr(fake, "_route", lambda path, params: [{"id": "big", "blob": "x" * 200_000}, {"id": "small"}])
    result = await call("kitsu_get", path="data/whatever")
    assert result["truncated"] is True and result["returned"] == 0 and len(str(result)) < 5_000
    monkeypatch.setattr(fake, "_route", lambda path, params: {"blob": "x" * 200_000})
    result = await call("kitsu_get", path="data/whatever")
    assert result["truncated"] is True and "preview" not in result


async def test_asset_types_match_project_names_by_containment(call, fake):
    """Projects name types differently ("Characters - PFE 2028"); a shorter name still finds them."""
    fake.data["asset_types"].append({"id": "at-char-pfe", "name": "Character - PFE 2028"})
    fake.data["assets"][0]["asset_type_id"] = "at-char-pfe"
    fake.data["assets"][0]["asset_type_name"] = "Character - PFE 2028"
    result = await call("list_assets", project="p-1", asset_types=["character"])
    assert [a["name"] for a in result["assets"]] == ["Hero"]
    excluded = await call("list_assets", project="p-1", exclude_asset_types=["Character"])
    assert [a["name"] for a in excluded["assets"]] == ["Forest"]


async def test_asset_type_exact_name_wins_over_containment(call, fake):
    fake.data["asset_types"].append({"id": "at-char-2", "name": "Character Props"})
    fake.data["assets"].append(
        {
            **fake.data["assets"][0],
            "id": "a-cp",
            "name": "Hat",
            "asset_type_id": "at-char-2",
            "asset_type_name": "Character Props",
        }
    )
    result = await call("list_assets", project="p-1", asset_types=["Character"])
    assert [a["name"] for a in result["assets"]] == ["Hero"]


async def test_search_tasks_compact_rows(call):
    compact = await call("search_tasks", project="p-1", task_types=["COMP"])
    assert set(compact["tasks"][0]) == {"id", "entity", "task_type", "status", "assignees", "due_date"}
    full = await call("search_tasks", project="p-1", task_types=["COMP"], detail="full")
    assert {"entity_id", "group", "estimation", "last_preview_file_id"} <= set(full["tasks"][0])


async def test_list_people_and_playlists_page(call):
    people = await call("list_people", limit=1, offset=1)
    assert people["total"] == 2 and [p["full_name"] for p in people["people"]] == ["Bob Leroy"]
    playlists = await call("list_playlists", project="p-1", limit=1)
    assert playlists["total"] == 1 and len(playlists["playlists"]) == 1


async def test_project_overview_task_type_filters(call):
    everything = await call("project_overview", project="p-1")
    shots_only = await call("project_overview", project="p-1", exclude_task_types=["Modeling"])
    assert (everything["tasks"], shots_only["tasks"]) == (5, 3)
    assert shots_only["assets"] == everything["assets"]  # entity counts are not filtered
    assert {t["task_type"] for t in shots_only["by_task_type"]} == {"Animation", "Compositing"}
    anim = await call("project_overview", project="p-1", task_types=["ANIM"])
    assert (anim["tasks"], anim["done_ratio"]) == (2, 0.5)


async def test_whoami_describes_the_server(call, fake):
    result = await call("whoami")
    assert result["full_name"] == "Alice Martin"  # unchanged user fields
    server = result["server"]
    assert server["kitsu_host"] == "http://kitsu.test/api" and server["write_tools"] is False
    assert server["max_page_size"] == 500 and server["version"]
    assert server["status_role_settings"]["KITSU_DONE_STATUSES"] == ["cbb"]
    assert "password" not in str(result).lower() and server["kitsu_host"] != "p"
