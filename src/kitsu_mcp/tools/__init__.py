"""Tool modules, one per area. Importing this package registers every tool on `kitsu_mcp.server.app.mcp`.

Which tools an agent sees first is not decided here but by each tool's group tag (core, browse, activity,
planning, review, write; see kitsu_mcp.server.groups).
"""

from kitsu_mcp.tools import (
    activity,
    assets,
    custom_fields,
    meta,
    people,
    planning,
    projects,
    review,
    shots,
    tasks,
    write,
)

__all__ = [
    "activity",
    "assets",
    "custom_fields",
    "meta",
    "people",
    "planning",
    "projects",
    "review",
    "shots",
    "tasks",
    "write",
]
