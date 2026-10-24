from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import comment, task_detail
from kitsu_mcp.models import MyTask, TaskDetail


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def get_task(task_id: str, include_comments: bool = True, comment_limit: int = 20) -> TaskDetail:
    """Get a task with its entity, status, assignees and latest comments (newest first)."""
    client = get_client()
    result = task_detail(client.get(f"data/tasks/{task_id}/full"))
    if include_comments:
        result.comments = [comment(c) for c in client.get(f"data/tasks/{task_id}/comments")[:comment_limit]]
    return result


@mcp.tool(annotations=READ_ONLY, tags={"tasks"})
def my_tasks() -> list[MyTask]:
    """List open tasks assigned to the logged-in user."""
    return [
        MyTask(
            id=t["id"],
            project=t.get("project_name"),
            entity=t.get("entity_name"),
            entity_type=t.get("entity_type_name"),
            task_type=t.get("task_type_name"),
            status=t.get("task_status_short_name"),
            due_date=t.get("due_date"),
        )
        for t in get_client().get("data/user/tasks")
    ]
