"""Kitsu MCP server: the FastMCP app with every tool module registered."""

from kitsu_mcp import tools  # noqa: F401  (registers tools)
from kitsu_mcp.app import mcp

__all__ = ["mcp"]
