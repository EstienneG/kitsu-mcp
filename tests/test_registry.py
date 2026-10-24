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
