"""Tools that modify Kitsu. Registered disabled; `main()` enables them when KITSU_ALLOW_WRITE=true.

Every write tool takes dry_run=True, which runs the same checks with reads only and returns the plan.
"""

from kitsu_mcp.tools.write import (
    assignments,
    breakdown,
    comments,
    config,
    lifecycle,
    playlists,
    schedule,
    structure,
    time,
)

__all__ = ["assignments", "breakdown", "comments", "config", "lifecycle", "playlists", "schedule", "structure", "time"]
