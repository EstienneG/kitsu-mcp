async def test_list_people(call, fake):
    fake.data["people"].append({"id": "bot", "full_name": "CI Bot", "is_bot": True, "active": True})
    fake.data["people"].append({"id": "gone", "full_name": "Zed Old", "active": False})
    assert [p["full_name"] for p in await call("list_people")] == ["Alice Martin", "Bob Leroy"]
    assert len(await call("list_people", include_inactive=True)) == 3
    assert len(await call("list_people", project="Demo Short")) == 2


async def test_my_tasks_only_open(call):
    assert {t["id"] for t in await call("my_tasks")} == {"t-hero-mod"}


async def test_get_person_tasks(call):
    assert [t["id"] for t in await call("get_person_tasks", person="Bob Leroy")] == ["t-sh010-comp", "t-forest-mod"]
    assert [t["id"] for t in await call("get_person_tasks", person="alice", done=True)] == ["t-sh010-anim"]


async def test_workload(call):
    rows = {w["person"]: w for w in await call("workload", project="Demo Short")}
    assert rows["Bob Leroy"] == {
        "person": "Bob Leroy",
        "open_tasks": 2,
        "overdue": 1,
        "waiting_feedback": 0,
        "retakes": 1,
        "estimation": 720,
        "logged": 60,
        "next_due": "2026-10-10",
    }
    assert rows["Alice Martin"]["waiting_feedback"] == 1
    assert rows["(unassigned)"]["open_tasks"] == 1


async def test_workload_by_task_type(call):
    assert [w["person"] for w in await call("workload", project="p-1", task_types=["Modeling"])] == [
        "Alice Martin",
        "Bob Leroy",
    ]


async def test_project_overview(call):
    overview = await call("project_overview", project="Demo Short")
    assert (overview["assets"], overview["shots"], overview["tasks"]) == (2, 2, 5)
    assert overview["done_ratio"] == 0.2
    assert (overview["overdue"], overview["waiting_feedback"], overview["retakes"]) == (2, 1, 1)
    assert overview["unassigned_open"] == 1
    animation = next(t for t in overview["by_task_type"] if t["task_type"] == "Animation")
    assert animation == {
        "task_type": "Animation",
        "total": 2,
        "done": 1,
        "done_ratio": 0.5,
        "statuses": [{"status": "done", "count": 1}, {"status": "todo", "count": 1}],
    }


async def test_project_overview_counts_entities_without_tasks(call, fake):
    fake.data["assets"].append({**fake.data["assets"][1], "id": "a-new", "name": "Bridge"})
    fake.data["assets"].append({**fake.data["assets"][1], "id": "a-cut", "name": "Cut", "canceled": True})
    overview = await call("project_overview", project="p-1")
    assert (overview["assets"], overview["tasks"]) == (3, 5)
