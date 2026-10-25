"""The MCP server: the FastMCP app with every tool, resource and prompt registered.

`kitsu_mcp.server:mcp` is the app hosting platforms import. The modules here are what is MCP-facing besides
the tools: the app and its `@tool` decorator (app), tool groups and load_tools (groups), the HTTP transport
(http), prompts and resources.
"""

from kitsu_mcp import tools  # noqa: F401  (registration side effects)
from kitsu_mcp.server import groups, http, prompts, resources  # noqa: F401
from kitsu_mcp.server.app import mcp

# Write tools stay hidden unless KITSU_ALLOW_WRITE=true (see kitsu_mcp.main), in both stdio and HTTP mode.
mcp.disable(tags={"write"})

__all__ = ["mcp"]
