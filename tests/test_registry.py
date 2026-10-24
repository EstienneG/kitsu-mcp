"""Guards that keep the README tool table honest."""

import re
from pathlib import Path

from kitsu_mcp.server import mcp


async def test_readme_lists_every_tool():
    mcp.enable(tags={"write"})
    try:
        tools = {t.name for t in await mcp.list_tools()}
    finally:
        mcp.disable(tags={"write"})
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    documented = set(re.findall(r"`([a-z_]+)`", readme.split("## Tools", 1)[1]))
    assert tools - documented == set(), "tools missing from README"


async def test_every_tool_has_a_description_and_annotations():
    for tool in await mcp.list_tools():
        assert tool.description, tool.name
        assert tool.annotations is not None, tool.name


async def test_output_schemas_are_generic_and_arguments_kept():
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
