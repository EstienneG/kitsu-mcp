"""Kitsu MCP server: the FastMCP app with every tool, resource and prompt registered."""

from kitsu_mcp import prompts, resources, tools  # noqa: F401  (registration side effects)
from kitsu_mcp.app import mcp

# Write tools stay hidden unless KITSU_ALLOW_WRITE=true (see kitsu_mcp.main).
mcp.disable(tags={"write"})

__all__ = ["mcp"]
