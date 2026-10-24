"""The shared FastMCP instance. Tool modules register on it when imported."""

import functools

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent

mcp = FastMCP(
    "kitsu",
    instructions=(
        "Access to a Kitsu production tracker. Tools accept project, task type, status and "
        "person names as well as IDs (case-insensitive). Status filters use task status short "
        "names (e.g. wip, wfa, done); list_task_statuses shows them and the role each one plays here "
        "(done, omitted, on hold, waiting review, ...), which every count and filter follows. Durations "
        'and estimates are in minutes. List tools return compact rows by default (detail="full" for '
        "more). Use kitsu_get for any read the other tools don't cover. Write tools "
        "(comments, status changes, assignments, schedule, time logs) only exist when the server "
        "runs with KITSU_ALLOW_WRITE=true; confirm with the user before calling them."
    ),
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}


def tool(**kwargs):
    """Register a tool on `mcp` without publishing an output schema.

    Results are still JSON; leaving their schemas out of the tool list roughly halves what every session
    pays in context before any call (the field docs that matter are in the docstrings). Without a schema
    an empty list would come back as no content at all, so it is sent as an explicit "[]".
    """

    def register(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kw):
            result = fn(*args, **kw)
            if isinstance(result, list) and not result:
                return ToolResult(content=[TextContent(type="text", text="[]")])
            return result

        return mcp.tool(output_schema=None, **kwargs)(wrapper)

    return register
