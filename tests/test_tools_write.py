import pytest
from fastmcp.exceptions import ToolError

from kitsu_mcp.server import mcp
from tests.fakes import ALICE, BOB, ST_DONE, ST_WFA

WRITE_TOOLS = {"add_comment", "set_task_status", "assign_task", "update_task_schedule", "log_time"}


@pytest.fixture
def writable():
    mcp.enable(tags={"write"})
    yield
    mcp.disable(tags={"write"})


def writes(fake):
    return [(method, path, data) for method, path, data in fake.calls if method != "GET"]


async def test_write_tools_hidden_by_default():
    assert not WRITE_TOOLS & {t.name for t in await mcp.list_tools()}


async def test_write_tools_are_annotated(writable):
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) >= WRITE_TOOLS
    for name in WRITE_TOOLS:
        assert tools[name].annotations.read_only_hint is False


async def test_add_comment_keeps_status_by_default(call, fake, writable):
    result = await call("add_comment", task_id="t-hero-mod", text="Looks good")
    assert result["message"] == "Comment posted."
    assert writes(fake) == [
        ("POST", "actions/tasks/t-hero-mod/comment", {"task_status_id": ST_WFA, "comment": "Looks good"})
    ]


async def test_add_comment_with_status(call, fake, writable):
    result = await call("add_comment", task_id="t-hero-mod", text="Approved", status="DONE")
    assert result["message"] == "Comment posted; status set to done."
    assert writes(fake)[0][2]["task_status_id"] == ST_DONE


async def test_add_empty_comment_rejected(call, fake, writable):
    with pytest.raises(ToolError, match="empty"):
        await call("add_comment", task_id="t-hero-mod", text="  ")
    assert writes(fake) == []


async def test_set_task_status(call, fake, writable):
    result = await call("set_task_status", task_id="t-hero-mod", status="done")
    assert result["message"] == "Status changed from wfa to done."
    assert result["task"]["entity"] == "Hero"


async def test_set_unknown_status_writes_nothing(call, fake, writable):
    with pytest.raises(ToolError, match="Unknown task status"):
        await call("set_task_status", task_id="t-hero-mod", status="approvedd")
    assert writes(fake) == []


async def test_assign_task(call, fake, writable):
    await call("assign_task", task_id="t-sh020-anim", person="bob")
    assert writes(fake) == [("PUT", f"actions/persons/{BOB}/assign", {"task_ids": ["t-sh020-anim"]})]


async def test_update_task_schedule(call, fake, writable):
    await call("update_task_schedule", task_id="t-hero-mod", due_date="2026-11-01", estimation_minutes=120)
    assert writes(fake) == [("PUT", "data/tasks/t-hero-mod", {"due_date": "2026-11-01", "estimation": 120})]


@pytest.mark.parametrize(
    "args, error",
    [({}, "Nothing to update"), ({"due_date": "next friday"}, "YYYY-MM-DD"), ({"estimation_minutes": -1}, ">= 0")],
)
async def test_update_task_schedule_validation(call, fake, writable, args, error):
    with pytest.raises(ToolError, match=error):
        await call("update_task_schedule", task_id="t-hero-mod", **args)
    assert writes(fake) == []


async def test_log_time_defaults_to_me(call, fake, writable):
    await call("log_time", task_id="t-hero-mod", minutes=90, day="2026-10-14")
    assert writes(fake) == [
        ("POST", f"actions/tasks/t-hero-mod/time-spents/2026-10-14/persons/{ALICE}/add", {"duration": 90})
    ]


async def test_log_time_bounds(call, fake, writable):
    with pytest.raises(ToolError, match="between 1 and 1440"):
        await call("log_time", task_id="t-hero-mod", minutes=0)
