"""HTTP transport: the server hosted for web agents (custom MCP connectors).

Every caller logs in to Kitsu with their own credentials (see kitsu_mcp.auth). Tools that only make sense on
the caller's machine (writing files to a folder) are hidden over HTTP. That is enforced per request, so it
also holds when a platform imports `kitsu_mcp.server:mcp` directly instead of running `kitsu-mcp --http`.
Write tools follow KITSU_ALLOW_WRITE in both modes.
"""

import ipaddress
import sys

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from kitsu_mcp.app import mcp

LOCAL_TAG = "local"
"""Tools that write files on the machine running the server: useless (and unsafe) when it is hosted."""


def over_http() -> bool:
    try:
        get_http_request()
    except RuntimeError:
        return False
    return True


class HttpToolPolicy(Middleware):
    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        if not over_http():
            return tools
        return [t for t in tools if LOCAL_TAG not in t.tags]

    async def on_call_tool(self, context, call_next):
        if over_http():
            tool = await mcp.get_tool(context.message.name)
            if tool is not None and LOCAL_TAG in tool.tags:
                raise ToolError(f"{context.message.name} is not available on the hosted server")
        return await call_next(context)


mcp.add_middleware(HttpToolPolicy())


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def run(host: str, port: int, behind_tls: bool) -> None:
    """Serve MCP at http://host:port/mcp. Callers send their Kitsu login in plain HTTP headers, so anything
    but a loopback bind needs a TLS-terminating proxy in front (hosting platforms provide one)."""
    if not _is_loopback(host) and not behind_tls:
        sys.exit(
            f"Refusing to listen on {host} without TLS: callers send their Kitsu password with every request. "
            "Put the server behind HTTPS (Fly.io, Render, a reverse proxy) and pass --behind-tls, "
            "or bind to 127.0.0.1 for local testing."
        )
    print(
        f"kitsu-mcp: serving MCP on http://{host}:{port}/mcp (each caller logs in with their own Kitsu account; "
        "use HTTPS in front)",
        file=sys.stderr,
    )
    mcp.run(transport="http", host=host, port=port, show_banner=False)
