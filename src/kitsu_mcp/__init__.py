"""MCP server for the Kitsu (CGWire) production tracker."""


def main() -> None:
    from kitsu_mcp.server import mcp

    mcp.run()
