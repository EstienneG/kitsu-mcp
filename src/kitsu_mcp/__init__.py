"""MCP server for the Kitsu (CGWire) production tracker."""

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="kitsu-mcp", description=__doc__)
    parser.add_argument("--http", action="store_true", help="serve over HTTP (hosted connector) instead of stdio")
    parser.add_argument("--host", default=os.environ.get("KITSU_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--behind-tls",
        action="store_true",
        default=os.environ.get("KITSU_BEHIND_TLS", "").lower() in ("1", "true", "yes"),
        help="confirm HTTPS terminates in front of the server (required to bind a non-loopback host)",
    )
    args = parser.parse_args()

    from kitsu_mcp.config import get_settings, require_login
    from kitsu_mcp.server import groups, mcp

    settings = get_settings()
    if not args.http:
        require_login(settings)
    if settings.allow_write:
        mcp.enable(tags={"write"})
    groups.set_default_groups(settings.tool_groups)
    if args.http:
        from kitsu_mcp.server import http

        http.run(args.host, args.port, args.behind_tls)
    else:
        mcp.run()
