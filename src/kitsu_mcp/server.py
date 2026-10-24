"""Kitsu MCP server: the FastMCP app with every tool, resource and prompt registered."""

from kitsu_mcp import prompts, resources, tools  # noqa: F401  (registration side effects)
from kitsu_mcp.app import mcp

__all__ = ["mcp"]
