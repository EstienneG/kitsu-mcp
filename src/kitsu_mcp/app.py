"""The shared FastMCP instance. Tool modules register on it when imported."""

from fastmcp import FastMCP

mcp = FastMCP(
    "kitsu",
    instructions=(
        "Access to a Kitsu production tracker. Tools accept project, task type, status and "
        "person names as well as IDs (case-insensitive). Status filters use task status short "
        "names (e.g. wip, wfa, done); list_task_statuses shows them. Durations and estimates "
        "are in minutes. Use kitsu_get for any read the other tools don't cover. Write tools "
        "(comments, status changes, assignments, schedule, time logs) only exist when the server "
        "runs with KITSU_ALLOW_WRITE=true; confirm with the user before calling them."
    ),
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}
