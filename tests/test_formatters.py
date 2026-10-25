from kitsu_mcp.kitsu.formatters import comment, task_summary
from kitsu_mcp.kitsu.lookups import Lookups
from tests.fake_data import ALICE, ST_WFA, TT_MODEL
from tests.fakes import FakeClient


def test_comment_author_falls_back_to_first_and_last_name():
    assert comment({"person": {"first_name": "Alice", "last_name": "Martin"}}).author == "Alice Martin"
    assert comment({"person": {"full_name": "Bob Leroy"}}).author == "Bob Leroy"


def test_comment_without_person_has_no_author():
    assert comment({"person": None, "task_status": None}).author is None


def test_comment_collects_preview_ids():
    assert comment({"previews": [{"id": "pf-1"}, {"id": "pf-2"}]}).preview_ids == ["pf-1", "pf-2"]


def test_task_summary_resolves_names_and_keeps_unknown_assignee_ids():
    lookups = Lookups(FakeClient(), ttl=300)  # type: ignore[arg-type]
    summary = task_summary(
        {"id": "t", "task_type_id": TT_MODEL, "task_status_id": ST_WFA, "assignees": [ALICE, "ghost"]}, lookups
    )
    assert summary.task_type == "Modeling"
    assert summary.status == "wfa"
    assert summary.assignees == ["Alice Martin", "ghost"]
