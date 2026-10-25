"""Guards that keep the README tool table honest."""

import re
from pathlib import Path

from kitsu_mcp.server import mcp


async def test_readme_lists_every_tool(all_groups):
    mcp.enable(tags={"write"})
    try:
        tools = {t.name for t in await mcp.list_tools()}
    finally:
        mcp.disable(tags={"write"})
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    documented = set(re.findall(r"`([a-z_]+)`", readme.split("## Tools", 1)[1]))
    assert tools - documented == set(), "tools missing from README"


async def test_every_tool_has_a_description_and_annotations(all_groups):
    for tool in await mcp.list_tools():
        assert tool.description, tool.name
        assert tool.annotations is not None, tool.name


async def test_output_schemas_are_generic_and_arguments_kept(all_groups):
    """Detailed output schemas are left out to save context; the input schemas must be unchanged."""
    tools = {t.name: t for t in await mcp.list_tools()}
    for name, t in tools.items():
        returns_images = name in {
            "get_preview",
            "get_video_contact_sheet",
            "get_video_frames",
            "compare_revisions",
            "review_video",
        }
        assert (t.output_schema is None) == returns_images, name
    assert set(tools["search_tasks"].parameters["properties"]) >= {"project", "detail", "limit", "group_by"}
    assert tools["search_tasks"].parameters["required"] == ["project"]


async def test_results_stay_structured_for_clients(fake):
    from fastmcp import Client

    async with Client(mcp) as client:
        empty = await client.call_tool("list_episodes", {"project": "p-1"})
        projects = await client.call_tool("list_projects", {})
    assert empty.data == [] and empty.structured_content == {"result": []}
    assert projects.data[0]["name"] == "Demo Short"


def test_tool_functions_are_callable_directly(fake):
    """Resources call tool functions; registration must not wrap them."""
    from kitsu_mcp.tools.projects import list_projects

    fake.data["projects"] = []
    assert list_projects() == []


# What clients put in the model's context before any call: every tool's name, description and input schema.
# 68.6k characters (about 17k tokens) with every group and write tools on, as of 74 tools. Most sessions
# only list the core tools (see test_groups). Raise this deliberately, with the
# README's "Context cost" paragraph, when a new tool earns its place.
TOOL_LIST_BUDGET_CHARS = 70_000


async def test_tool_list_stays_within_its_context_budget(all_groups):
    """The whole list, every group listed (KITSU_TOOL_GROUPS=all): without all_groups the group filter would
    hide most tools and the budget would measure only the core list."""
    import json

    mcp.enable(tags={"write"})
    try:
        tools = await mcp.list_tools()
    finally:
        mcp.disable(tags={"write"})
    size = sum(
        len(
            json.dumps(
                {"name": t.name, "description": t.description, "input_schema": t.parameters}, separators=(",", ":")
            )
        )
        for t in tools
    )
    assert size <= TOOL_LIST_BUDGET_CHARS, f"tool list is {size} characters, over the {TOOL_LIST_BUDGET_CHARS} budget"


def test_kitsu_package_does_not_depend_on_server_or_tools():
    """kitsu/ is the Kitsu side; the server and tools build on it, never the other way round."""
    import ast

    forbidden = ("kitsu_mcp.server", "kitsu_mcp.tools")
    for path in (Path(__file__).parents[1] / "src" / "kitsu_mcp" / "kitsu").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                raise AssertionError(f"{path.name}: use absolute imports in kitsu/ (found a relative one)")
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                # `from kitsu_mcp import server` imports kitsu_mcp.server too.
                modules = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            else:
                continue
            for module in modules:
                assert not (module + ".").startswith(tuple(f + "." for f in forbidden)), (path.name, module)


def test_readme_lists_every_tool_group():
    """The group map in server/app.py is what agents read; the README's table must cover the same groups."""
    from kitsu_mcp.server.app import GROUPS

    table = (Path(__file__).parents[1] / "README.md").read_text().split("| Group | Tools |", 1)[1].split("\n\n", 1)[0]
    assert set(re.findall(r"^\| `([a-z]+)`", table, flags=re.M)) == set(GROUPS)
