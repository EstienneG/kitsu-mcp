"""MCP server for the Kitsu (CGWire) production tracker."""


def main() -> None:
    from kitsu_mcp.config import get_settings
    from kitsu_mcp.server import mcp

    if get_settings().allow_write:
        mcp.enable(tags={"write"})
    mcp.run()
