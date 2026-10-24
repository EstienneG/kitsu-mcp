async def ids(call, **args):
    return [t["id"] for t in (await call("search_tasks", project="Demo Short", **args))["tasks"]]


async def test_search_all_tasks_sorted_by_due_date_missing_last(call):
    assert await ids(call) == ["t-sh010-anim", "t-hero-mod", "t-sh010-comp", "t-forest-mod", "t-sh020-anim"]


async def test_search_row_has_entity_context(call):
    row = (await call("search_tasks", project="p-1", task_types=["COMP"]))["tasks"][0]
    assert row["entity"] == "SH010"
    assert row["entity_kind"] == "shot"
    assert row["group"] == "SQ010"
    assert row["assignees"] == ["Bob Leroy"]


async def test_search_filters(call):
    assert await ids(call, task_types=["animation"], statuses=["todo"]) == ["t-sh020-anim"]
    assert await ids(call, assignee="alice", entity_kind="asset") == ["t-hero-mod"]
    assert await ids(call, unassigned=True) == ["t-sh020-anim"]
    assert await ids(call, group="environment") == ["t-forest-mod"]
    assert await ids(call, entity_name_contains="sh01", include_done=False) == ["t-sh010-comp"]
    assert await ids(call, due_after="2026-10-01", due_before="2026-10-10") == ["t-hero-mod", "t-sh010-comp"]


async def test_search_overdue_excludes_done(call):
    assert await ids(call, overdue=True) == ["t-hero-mod", "t-sh010-comp"]


async def test_search_pagination_and_sort(call):
    result = await call("search_tasks", project="p-1", sort_by="entity", limit=2, offset=1)
    assert result["total"] == 5
    assert [t["entity"] for t in result["tasks"]] == ["Hero", "SH010"]


async def test_task_history(call):
    history = await call("task_history", task_id="t-hero-mod")
    assert history["current_status"] == "wfa"
    assert history["time_logged"] == 600
    assert [(c["previous_status"], c["status"]) for c in history["changes"]] == [(None, "wip"), ("wip", "wfa")]
