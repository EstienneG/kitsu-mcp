"""MCP resources: read-only views clients can attach as context."""

from kitsu_mcp.app import mcp
from kitsu_mcp.tools.projects import list_projects, list_task_statuses, list_task_types, project_overview
from kitsu_mcp.tools.tasks import get_task


@mcp.resource("kitsu://projects", mime_type="application/json", description="Open productions")
def projects_resource() -> list[dict]:
    return [p.model_dump() for p in list_projects()]


@mcp.resource("kitsu://task-types", mime_type="application/json", description="Task types")
def task_types_resource() -> list[dict]:
    return [t.model_dump() for t in list_task_types()]


@mcp.resource("kitsu://task-statuses", mime_type="application/json", description="Task statuses and their flags")
def task_statuses_resource() -> list[dict]:
    return [s.model_dump() for s in list_task_statuses()]


@mcp.resource(
    "kitsu://projects/{project}/overview",
    mime_type="application/json",
    description="Progress overview of a project (name or ID)",
)
def project_overview_resource(project: str) -> dict:
    return project_overview(project).model_dump()


@mcp.resource("kitsu://tasks/{task_id}", mime_type="application/json", description="A task with its latest comments")
def task_resource(task_id: str) -> dict:
    return get_task(task_id).model_dump()
