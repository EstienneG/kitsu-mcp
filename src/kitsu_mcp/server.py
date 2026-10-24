"""Read-only MCP server for a Kitsu (Zou) instance.

Configuration comes from environment variables or a `.env` file in the working directory:
KITSU_HOST (e.g. https://example.cg-wire.com/api), KITSU_USER, KITSU_PASSWORD.
"""

import os
from pathlib import Path

import gazu
from fastmcp import FastMCP

mcp = FastMCP(
    "kitsu",
    instructions=(
        "Read-only access to a Kitsu production tracker. Resolve names to IDs with "
        "list_projects, list_task_types and list_task_statuses before filtering. "
        "Status filters use task status short names (e.g. wip, wfa, done)."
    ),
)

_ready = False


def _load_env() -> None:
    env_file = Path.cwd() / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _client():
    global _ready
    if not _ready:
        _load_env()
        missing = [k for k in ("KITSU_HOST", "KITSU_USER", "KITSU_PASSWORD") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"Missing configuration: {', '.join(missing)}")
        gazu.set_host(os.environ["KITSU_HOST"])
        gazu.log_in(os.environ["KITSU_USER"], os.environ["KITSU_PASSWORD"])
        _ready = True
    return gazu.client


def _get(path: str, params: dict | None = None):
    return _client().get(path, params=params)


def _index(path: str) -> dict:
    return {item["id"]: item for item in _get(path)}


def _compact_task(task: dict, task_types: dict, statuses: dict, people: dict) -> dict:
    status = statuses.get(task.get("task_status_id"), {})
    return {
        "id": task["id"],
        "task_type": task_types.get(task.get("task_type_id"), {}).get("name"),
        "status": status.get("short_name"),
        "assignees": [people.get(a, {}).get("full_name", a) for a in task.get("assignees", [])],
        "due_date": task.get("due_date"),
    }


@mcp.tool
def whoami() -> dict:
    """Return the Kitsu user the server is logged in as."""
    user = _get("auth/authenticated")["user"]
    return {k: user.get(k) for k in ("id", "full_name", "email", "role")}


@mcp.tool
def list_projects(include_closed: bool = False) -> list[dict]:
    """List productions (open ones by default)."""
    projects = _get("data/projects" if include_closed else "data/projects/open")
    return [{k: p.get(k) for k in ("id", "name", "production_type", "project_status_id")} for p in projects]


@mcp.tool
def list_task_types() -> list[dict]:
    """List task types (Modelling, Sculpting, ...) with their entity kind."""
    return [{k: t.get(k) for k in ("id", "name", "short_name", "for_entity")} for t in _get("data/task-types")]


@mcp.tool
def list_task_statuses() -> list[dict]:
    """List task statuses with their short names (wip, wfa, done, ...)."""
    return [{k: s.get(k) for k in ("id", "name", "short_name", "is_done")} for s in _get("data/task-status")]


@mcp.tool
def list_asset_types(project_id: str) -> list[dict]:
    """List asset types used in a project."""
    return [{"id": t["id"], "name": t["name"]} for t in _get(f"data/projects/{project_id}/asset-types")]


@mcp.tool
def list_assets(
    project_id: str,
    asset_types: list[str] | None = None,
    exclude_asset_types: list[str] | None = None,
    task_status_filters: dict[str, list[str]] | None = None,
    name_contains: str | None = None,
    limit: int = 200,
) -> dict:
    """List a project's assets with their tasks, optionally filtered.

    asset_types / exclude_asset_types: asset type names (e.g. ["Environment"]).
    task_status_filters: task type name -> allowed status short names; all must match,
    e.g. {"Modelling": ["APP", "wip"], "Sculpting": ["WRA"]}. Matching is case-insensitive.
    """
    task_types = _index("data/task-types")
    statuses = _index("data/task-status")
    people = _index("data/persons")
    asset_type_names = {t["id"]: t["name"] for t in _get("data/asset-types")}

    include = {n.lower() for n in asset_types or []}
    exclude = {n.lower() for n in exclude_asset_types or []}
    status_filters = {
        tt.lower(): {s.lower() for s in allowed} for tt, allowed in (task_status_filters or {}).items()
    }

    results = []
    for asset in _get("data/assets/with-tasks", params={"project_id": project_id}):
        type_name = asset_type_names.get(asset.get("entity_type_id"), "")
        if include and type_name.lower() not in include:
            continue
        if exclude and type_name.lower() in exclude:
            continue
        if name_contains and name_contains.lower() not in asset.get("name", "").lower():
            continue
        tasks = [_compact_task(t, task_types, statuses, people) for t in asset.get("tasks", [])]
        by_type = {(t["task_type"] or "").lower(): (t["status"] or "").lower() for t in tasks}
        if any(by_type.get(tt) not in allowed for tt, allowed in status_filters.items()):
            continue
        results.append(
            {"id": asset["id"], "name": asset["name"], "type": type_name, "tasks": tasks}
        )

    return {"total": len(results), "assets": results[:limit]}


@mcp.tool
def get_asset(asset_id: str) -> dict:
    """Get an asset's details and tasks."""
    asset = _get(f"data/assets/{asset_id}")
    task_types = _index("data/task-types")
    statuses = _index("data/task-status")
    people = _index("data/persons")
    tasks = _get(f"data/assets/{asset_id}/tasks")
    return {
        **{k: asset.get(k) for k in ("id", "name", "description", "project_id", "entity_type_id", "data")},
        "tasks": [_compact_task(t, task_types, statuses, people) for t in tasks],
    }


@mcp.tool
def get_task(task_id: str, include_comments: bool = True, comment_limit: int = 20) -> dict:
    """Get a task with its entity, status, assignees and latest comments."""
    task = _get(f"data/tasks/{task_id}/full")
    result = {
        "id": task["id"],
        "project": task.get("project", {}).get("name"),
        "entity": task.get("entity", {}).get("name"),
        "task_type": task.get("task_type", {}).get("name"),
        "status": task.get("task_status", {}).get("short_name"),
        "assignees": [p.get("full_name") for p in task.get("persons", [])],
        "due_date": task.get("due_date"),
        "estimation": task.get("estimation"),
        "duration": task.get("duration"),
    }
    if include_comments:
        comments = _get(f"data/tasks/{task_id}/comments")[:comment_limit]
        result["comments"] = [
            {
                "date": c.get("created_at"),
                "author": c.get("person", {}).get("first_name", "") + " " + c.get("person", {}).get("last_name", ""),
                "status": c.get("task_status", {}).get("short_name"),
                "text": c.get("text"),
            }
            for c in comments
        ]
    return result


@mcp.tool
def my_tasks() -> list[dict]:
    """List open tasks assigned to the logged-in user."""
    return [
        {
            "id": t["id"],
            "project": t.get("project_name"),
            "entity": t.get("entity_name"),
            "entity_type": t.get("entity_type_name"),
            "task_type": t.get("task_type_name"),
            "status": t.get("task_status_short_name"),
            "due_date": t.get("due_date"),
        }
        for t in _get("data/user/tasks")
    ]


@mcp.tool
def kitsu_get(path: str, params: dict | None = None):
    """Run a raw read-only GET on the Zou API, e.g. path="data/projects/open".

    See https://api-docs.kitsu.cloud/ for routes. Use for anything the other tools don't cover.
    """
    return _get(path.lstrip("/").removeprefix("api/"), params)

