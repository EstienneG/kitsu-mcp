"""Status roles: one meaning per status, from the KITSU_*_STATUSES settings first, then Kitsu's flags."""

import pytest

from kitsu_mcp.lookups import Lookups
from tests.fakes import FakeClient

STATUSES = [
    # CBB on the live instance is flagged both retake and feedback request; the studio means "done".
    {"id": "st-cbb", "name": "Could be better", "short_name": "CBB", "is_retake": True, "is_feedback_request": True},
    {"id": "st-standby", "name": "Stand by", "short_name": "STAND BY", "is_wip": False},
    {"id": "st-pause", "name": "Pause", "short_name": "PAUSE", "is_wip": True},
    {"id": "st-omit", "name": "OMIT", "short_name": "OMIT", "is_done": True},
    {"id": "st-wfa-s", "name": "WFA Supervisor", "short_name": "WFA_S", "is_wip": True},
]


@pytest.fixture
def lookups():
    fake = FakeClient()
    fake.data["statuses"] += STATUSES
    return Lookups(fake, ttl=300)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "status_id, role, source",
    [
        ("st-cbb", "done", "KITSU_DONE_STATUSES"),
        ("st-standby", "on_hold", "KITSU_ON_HOLD_STATUSES"),
        ("st-pause", "on_hold", "KITSU_ON_HOLD_STATUSES"),
        ("st-omit", "omitted", "KITSU_OMITTED_STATUSES"),
        ("st-wfa-s", "wip", "kitsu flags"),  # not flagged feedback in Kitsu; KITSU_REVIEW_STATUSES can say so
        ("st-done", "done", "kitsu flags"),
        ("st-retake", "retake", "kitsu flags"),
        ("st-wfa", "waiting_review", "kitsu flags"),
        ("st-wip", "wip", "kitsu flags"),
        ("st-todo", "todo", "kitsu flags"),
    ],
)
def test_default_roles(lookups, status_id, role, source):
    assert lookups.role_and_source(status_id) == (role, source)


def test_settings_override_flags_and_report_typos(lookups):
    lookups.client.settings.review_statuses = "wfa_s, wfa_r"
    lookups.client.settings.done_statuses = "cbb,not-a-status"
    assert lookups.role("st-wfa-s") == "waiting_review"
    assert lookups.unmatched_role_names() == {
        "KITSU_DONE_STATUSES": ["not-a-status"],
        "KITSU_REVIEW_STATUSES": ["wfa_r"],
    }


def test_first_matching_setting_wins(lookups):
    lookups.client.settings.on_hold_statuses = "cbb"  # also in done_statuses, which comes first
    assert lookups.role("st-cbb") == "done"


async def test_cbb_counts_as_done_and_improvable(call, fake):
    fake.data["statuses"] += STATUSES
    task = next(t for t in fake.data["tasks"] if t["id"] == "t-sh010-comp")  # was a retake, overdue
    task["task_status_id"] = "st-cbb"
    overview = await call("project_overview", project="p-1")
    # done: sh010 anim + sh010 comp (CBB) out of 5
    assert overview["done_ratio"] == 0.4
    assert (overview["done_improvable"], overview["done_improvable_statuses"]) == (1, ["CBB"])
    assert (overview["retakes"], overview["waiting_feedback"]) == (0, 1)  # CBB is neither
    assert overview["overdue"] == 1  # only hero modeling now
    assert "t-sh010-comp" not in [t["id"] for t in (await call("search_tasks", project="p-1", overdue=True))["tasks"]]


async def test_on_hold_tasks_are_open_but_never_overdue(call, fake):
    fake.data["statuses"] += STATUSES
    task = next(t for t in fake.data["tasks"] if t["id"] == "t-hero-mod")  # overdue wfa
    task["task_status_id"] = "st-standby"
    overview = await call("project_overview", project="p-1")
    assert (overview["on_hold"], overview["overdue"]) == (1, 1)
    alice = {w["person"]: w for w in await call("workload", project="p-1")}["Alice Martin"]
    assert (alice["open_tasks"], alice["on_hold"], alice["overdue"]) == (1, 1, 0)


async def test_omitted_tasks_are_left_out_of_search_by_default(call, fake):
    fake.data["statuses"] += STATUSES
    next(t for t in fake.data["tasks"] if t["id"] == "t-sh020-anim")["task_status_id"] = "st-omit"
    assert "t-sh020-anim" not in [t["id"] for t in (await call("search_tasks", project="p-1"))["tasks"]]
    assert "t-sh020-anim" in [
        t["id"] for t in (await call("search_tasks", project="p-1", include_omitted=True))["tasks"]
    ]
    asked = await call("search_tasks", project="p-1", statuses=["OMIT"])
    assert [t["id"] for t in asked["tasks"]] == ["t-sh020-anim"]
    overview = await call("project_overview", project="p-1")
    assert overview["omitted_statuses"] == ["OMIT"]


async def test_list_task_statuses_shows_roles(call, fake):
    fake.data["statuses"] += STATUSES
    result = await call("list_task_statuses")
    by_short = {s["short_name"]: s for s in result["statuses"]}
    assert (by_short["CBB"]["role"], by_short["CBB"]["role_source"]) == ("done", "KITSU_DONE_STATUSES")
    assert by_short["wfa"]["role"] == "waiting_review"
    # Defaults list spellings this fake studio lacks on purpose; only user-set names are reported.
    assert result["unmatched_settings"] == {}
