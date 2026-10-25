"""The shared FastMCP instance. Tool modules register on it when imported."""

import inspect

from fastmcp import FastMCP

# Here rather than in groups.py, which imports this module: the server instructions below need the map too.
GROUPS: dict[str, str] = {
    "browse": "list assets, shots, sequences, episodes, people, types; custom fields; casting",
    "activity": "what changed lately on a project; the user's notifications",
    "planning": "workload, timesheets with days off, quotas, schedule and milestones, budget",
    "review": "preview images, playlists, frame-level review of movies",
    "structure": "create, update, delete projects, episodes, sequences, shots, assets, concepts, edits, tasks "
    "(if the server allows writes)",
    "production": "start tasks, submit for review, publish previews, act on many tasks at once, edit or delete "
    "comments (if the server allows writes)",
    "admin": "production settings: team, task types and statuses used, custom fields, schedule and milestones, "
    "budgets (if the server allows writes)",
    "write": "comments, status changes, assignments, schedules, time logs, playlists (if the server allows)",
}
"""Tool groups load_tools adds, and what each holds: the one description the server instructions, load_tools
and the README follow (a test checks the README). A tool's group is its tag (see kitsu_mcp.server.groups)."""

# " | " between groups: the descriptions themselves use ";".
GROUP_SUMMARY = " | ".join(f"{name}: {holds}" for name, holds in GROUPS.items())

mcp = FastMCP(
    "kitsu",
    instructions=(
        "Access to a Kitsu production tracker. Tools accept project, task type, status and "
        "person names as well as IDs (case-insensitive). Status filters use task status short "
        "names (e.g. wip, wfa, done); list_task_statuses shows them and the role each one plays here "
        "(done, omitted, on hold, waiting review, ...), which every count and filter follows. Durations "
        'and estimates are in minutes. List tools return compact rows by default (detail="full" for '
        "more). Use kitsu_get for any read the other tools don't cover. Only the core tools are listed at "
        "first: call load_tools to add a group ("
        + GROUP_SUMMARY
        + "). Write tools only exist when the server runs with KITSU_ALLOW_WRITE=true. For write "
        "tools, call with dry_run=True first and show the user the plan before writing; then confirm with the "
        "user before calling them for real."
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
