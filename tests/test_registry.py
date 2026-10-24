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


async def test_no_output_schemas_and_arguments_kept():
    """Output schemas are left out to save context; the input schemas must survive the wrapper."""
    tools = {t.name: t for t in await mcp.list_tools()}
    assert all(t.output_schema is None for t in tools.values())
    assert set(tools["search_tasks"].parameters["properties"]) >= {"project", "detail", "limit", "group_by"}
    assert tools["search_tasks"].parameters["required"] == ["project"]


async def test_empty_list_results_are_explicit(fake):
    from fastmcp import Client

    async with Client(mcp) as client:
        result = await client.call_tool("list_episodes", {"project": "p-1"})
    assert [c.text for c in result.content] == ["[]"]
