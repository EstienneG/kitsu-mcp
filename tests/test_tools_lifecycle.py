"""Task lifecycle tools against the fake Kitsu, which does what Zou 1.0.97 did on a throwaway instance:
publishing chains comment -> add-preview -> upload, and deleting a comment deletes its previews."""

import pytest
from fastmcp.exceptions import ToolError

from tests.conftest import writes


def status(fake, task_id: str) -> str:
    task = next(t for t in fake.data["tasks"] if t["id"] == task_id)
    return next(s for s in fake.data["statuses"] if s["id"] == task["task_status_id"])["short_name"]


async def test_start_and_submit_for_review_pick_the_role_statuses(call, fake, writable):
    plan = await call("task_action", action="start", task_id="t-sh020-anim", dry_run=True)
    assert plan["after"] == {"status": "wip"} and writes(fake) == []
    await call("task_action", action="start", task_id="t-sh020-anim")
    assert status(fake, "t-sh020-anim") == "wip"
    await call("task_action", action="submit_for_review", task_id="t-sh020-anim", comment="ready")
    assert status(fake, "t-sh020-anim") == "wfa"  # the waiting_review role
    again = await call("task_action", action="submit_for_review", task_id="t-sh020-anim", dry_run=True)
    assert "already wfa" in again["warnings"][0]


async def test_publish_chains_three_requests_and_numbers_the_revision(call, fake, writable, tmp_path):
    movie = tmp_path / "sh020_v001.mp4"
    movie.write_bytes(b"\0" * 1024)
    plan = await call("publish_preview", task_id="t-sh020-anim", file_path=str(movie), set_main=True, dry_run=True)
    assert [r["method"] for r in plan["requests"]] == ["POST", "POST", "UPLOAD", "PUT"]
    assert plan["requests"][1]["path"].endswith("/comments/{0.id}/add-preview")  # filled from the comment's answer
    assert plan["requests"][2] == {
        "method": "UPLOAD",
        "path": "pictures/preview-files/{1.id}",
        "payload": {"file": str(movie)},
    }
    assert plan["after"]["revision"] == 1 and plan["after"]["status"] == "wfa"
    result = await call("publish_preview", task_id="t-sh020-anim", file_path=str(movie), comment="v1", set_main=True)
    preview = fake.data["preview_files"][result["id"]]
    assert preview["revision"] == 1 and preview["extension"] == "mp4" and preview["status"] == "ready"
    shot = next(s for s in fake.data["shots"] if s["id"] == "s-2")
    assert shot["preview_file_id"] == preview["id"]  # set_main
    upload = next(c for c in fake.calls if c[0] == "UPLOAD")
    assert upload[1] == f"pictures/preview-files/{preview['id']}"  # placeholder filled with the real ID
    nxt = await call("publish_preview", task_id="t-sh020-anim", file_path=str(movie), dry_run=True)
    assert nxt["after"]["revision"] == 2


async def test_publish_refuses_missing_files_and_warns_on_odd_ones(call, fake, writable, tmp_path):
    with pytest.raises(ToolError, match="No file at"):
        await call("publish_preview", task_id="t-sh020-anim", file_path=str(tmp_path / "nope.png"))
    odd = tmp_path / "notes.txt"
    odd.write_text("x")
    plan = await call("publish_preview", task_id="t-sh020-anim", file_path=str(odd), dry_run=True)
    assert any("may not preview .txt" in w for w in plan["warnings"])


async def test_batch_status_assign_priority_skip_what_is_already_so(call, fake, writable):
    ids = ["t-hero-mod", "t-sh010-anim", "t-sh020-anim"]
    plan = await call("batch_tasks", action="status", task_ids=ids, status="wip", dry_run=True)
    already = [t for t in ids if status(fake, t) == "wip"]
    assert len(plan["requests"]) == len(ids) - len(already)
    await call("batch_tasks", action="status", task_ids=ids, status="wip")
    assert all(status(fake, t) == "wip" for t in ids)
    assert (await call("batch_tasks", action="status", task_ids=ids, status="wip", dry_run=True))["requests"] == []
    await call("batch_tasks", action="assign", task_ids=ids, person="Bob Leroy")
    tasks = {t["id"]: t for t in fake.data["tasks"]}
    assert all("person-bob" in tasks[t]["assignees"] for t in ids)
    plan = await call("batch_tasks", action="unassign", task_ids=ids, person="Bob Leroy", dry_run=True)
    assert plan["requests"][0]["payload"] == {"task_ids": ids, "person_id": "person-bob"}
    await call("batch_tasks", action="priority", task_ids=ids, priority=3)
    assert all(tasks[t]["priority"] == 3 for t in ids)
    with pytest.raises(ToolError, match="between 0"):
        await call("batch_tasks", action="priority", task_ids=ids, priority=7)


async def test_batch_delete_sends_a_bare_array_and_needs_confirm(call, fake, writable):
    with pytest.raises(ToolError, match="confirm=True"):
        await call("batch_tasks", action="delete", task_ids=["t-sh020-anim"])
    plan = await call("batch_tasks", action="delete", task_ids=["t-sh020-anim"], confirm=True, dry_run=True)
    assert plan["requests"][0]["payload"] == ["t-sh020-anim"]  # Zou's bulk route takes a JSON array
    await call("batch_tasks", action="delete", task_ids=["t-sh020-anim"], confirm=True)
    assert all(t["id"] != "t-sh020-anim" for t in fake.data["tasks"])
    with pytest.raises(ToolError, match="At most 100"):
        await call("batch_tasks", action="status", task_ids=[f"t-{i}" for i in range(101)], status="wip")


async def test_comment_edit_and_delete_takes_its_previews(call, fake, writable, tmp_path):
    still = tmp_path / "f.png"
    still.write_bytes(b"png")
    published = await call("publish_preview", task_id="t-sh020-anim", file_path=str(still))
    comment = next(c for c in fake.data["comments"]["t-sh020-anim"] if c.get("previews"))
    await call("manage_comment", action="edit", task_id="t-sh020-anim", comment_id=comment["id"], text="v1 fixed")
    assert comment["text"] == "v1 fixed"
    plan = await call("manage_comment", action="delete", task_id="t-sh020-anim", comment_id=comment["id"], dry_run=True)
    assert any("deletes them with the comment" in w for w in plan["warnings"])
    with pytest.raises(ToolError, match="confirm=True"):
        await call("manage_comment", action="delete", task_id="t-sh020-anim", comment_id=comment["id"])
    await call("manage_comment", action="delete", task_id="t-sh020-anim", comment_id=comment["id"], confirm=True)
    assert published["id"] not in fake.data["preview_files"]
    with pytest.raises(ToolError, match="is not on task"):
        await call("manage_comment", action="edit", task_id="t-hero-mod", comment_id=comment["id"], text="x")


async def test_publish_is_hidden_on_the_hosted_server(writable):
    from kitsu_mcp.server import mcp

    tool = await mcp.get_tool("publish_preview")
    assert "local" in tool.tags  # the HTTP policy hides `local` tools and refuses their calls


async def test_text_that_looks_like_a_placeholder_is_sent_as_written(call, fake, writable):
    """Plans fill `{n.id}` in paths only: a comment containing "{0.id}" must go out exactly as the dry run showed."""
    text = "Rename with '{0.id}' template"
    plan = await call(
        "batch_tasks", action="status", task_ids=["t-sh020-anim"], status="wip", comment=text, dry_run=True
    )
    assert plan["requests"][0]["payload"]["comment"] == text
    await call("batch_tasks", action="status", task_ids=["t-sh020-anim"], status="wip", comment=text)
    assert fake.data["comments"]["t-sh020-anim"][0]["text"] == text
