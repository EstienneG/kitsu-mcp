"""The shared FastMCP instance. Tool modules register on it when imported."""

import inspect

from fastmcp import FastMCP

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


# One small schema for every data tool instead of a detailed one per tool: clients still get structured
# results (fastmcp's `.data`, `structured_content`), while the tool list stays about half the size.
_GENERIC_OUTPUT = {"type": "object", "properties": {"result": {}}, "x-fastmcp-wrap-result": True}


def tool(**kwargs):
    """Register a tool on `mcp` with a generic output schema instead of a detailed one.

    Detailed output schemas were half of what every session paid in context before any call; the field
    notes that matter are in the docstrings. Tools that can return images keep no schema at all, since
    images cannot be structured content. The decorated function itself is returned unchanged, so other
    modules (resources) can still call it directly.
    """

    def register(fn):
        returns = str(inspect.signature(fn).return_annotation)
        schema = None if "Image" in returns else _GENERIC_OUTPUT
        mcp.tool(output_schema=schema, **kwargs)(fn)
        return fn

    return register
