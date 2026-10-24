from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import Named, Project, TaskStatus, TaskType


@mcp.tool(annotations=READ_ONLY, tags={"projects"})
def list_projects(include_closed: bool = False) -> list[Project]:
    """List productions (open ones by default)."""
    lookups = get_lookups()
    projects = get_client().get("data/projects" if include_closed else "data/projects/open")
    return [
        Project(
            id=p["id"],
            name=p["name"],
            production_type=p.get("production_type"),
            status=lookups.name("project_statuses", p.get("project_status_id")),
        )
        for p in projects
    ]


@mcp.tool(annotations=READ_ONLY, tags={"projects"})
def list_task_types() -> list[TaskType]:
    """List task types (Modelling, Animation, ...) with the entity kind they apply to."""
    return [
        TaskType(id=t["id"], name=t["name"], short_name=t.get("short_name"), for_entity=t.get("for_entity"))
        for t in get_lookups().index("task_types").values()
        if not t.get("archived")
    ]


@mcp.tool(annotations=READ_ONLY, tags={"projects"})
def list_task_statuses() -> list[TaskStatus]:
    """List task statuses with their short names (wip, wfa, done, ...) and flags."""
    return [
        TaskStatus(
            id=s["id"],
            name=s["name"],
            short_name=s["short_name"],
            is_done=s.get("is_done"),
            is_wip=s.get("is_wip"),
            is_retake=s.get("is_retake"),
            is_feedback_request=s.get("is_feedback_request"),
        )
        for s in get_lookups().index("task_statuses").values()
        if not s.get("archived")
    ]


@mcp.tool(annotations=READ_ONLY, tags={"projects", "assets"})
def list_asset_types(project: str) -> list[Named]:
    """List asset types used in a project (name or ID)."""
    project_id = get_lookups().project(project)["id"]
    return [Named(id=t["id"], name=t["name"]) for t in get_client().get(f"data/projects/{project_id}/asset-types")]
