"""In-memory stand-in for the Kitsu API, seeded with a small invented production."""

import copy
import re
from typing import Any

from fastmcp.exceptions import ToolError

from kitsu_mcp.config import Settings

PROJECT = "p-1"
TT_MODEL, TT_ANIM, TT_COMP = "tt-model", "tt-anim", "tt-comp"
ST_WIP, ST_WFA, ST_DONE, ST_RETAKE, ST_TODO = "st-wip", "st-wfa", "st-done", "st-retake", "st-todo"
ALICE, BOB = "person-alice", "person-bob"


def seed() -> dict[str, Any]:
    task_types = [
        {"id": TT_MODEL, "name": "Modeling", "short_name": "MOD", "for_entity": "Asset"},
        {"id": TT_ANIM, "name": "Animation", "short_name": "ANIM", "for_entity": "Shot"},
        {"id": TT_COMP, "name": "Compositing", "short_name": "COMP", "for_entity": "Shot"},
        {"id": "tt-old", "name": "Old", "short_name": "OLD", "for_entity": "Asset", "archived": True},
    ]
    statuses = [
        {"id": ST_TODO, "name": "Todo", "short_name": "todo", "is_done": False, "is_default": True},
        {"id": ST_WIP, "name": "Work In Progress", "short_name": "wip", "is_done": False, "is_wip": True},
        {
            "id": ST_WFA,
            "name": "Waiting For Approval",
            "short_name": "wfa",
            "is_done": False,
            "is_feedback_request": True,
        },
        {"id": ST_RETAKE, "name": "Retake", "short_name": "retake", "is_done": False, "is_retake": True},
        {"id": ST_DONE, "name": "Done", "short_name": "done", "is_done": True},
    ]
    people = [
        {
            "id": ALICE,
            "full_name": "Alice Martin",
            "first_name": "Alice",
            "last_name": "Martin",
            "email": "alice@example.com",
            "desktop_login": "alice",
            "role": "user",
            "active": True,
        },
        {
            "id": BOB,
            "full_name": "Bob Leroy",
            "first_name": "Bob",
            "last_name": "Leroy",
            "email": "bob@example.com",
            "desktop_login": "bob",
            "role": "supervisor",
            "active": True,
        },
    ]
    projects = [
        {
            "id": PROJECT,
            "name": "Demo Short",
            "production_type": "short",
            "project_status_id": "ps-open",
            "fps": "24",
            "resolution": "1920x1080",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        {"id": "p-2", "name": "Closed Show", "production_type": "tvshow", "project_status_id": "ps-closed"},
    ]
    asset_types = [{"id": "at-char", "name": "Character"}, {"id": "at-env", "name": "Environment"}]
    assets = [
        {
            "id": "a-hero",
            "name": "Hero",
            "asset_type_id": "at-char",
            "asset_type_name": "Character",
            "entity_type_id": "at-char",
            "project_id": PROJECT,
            "description": "Main character",
            "data": {},
            "preview_file_id": "pf-hero",
            "canceled": False,
        },
        {
            "id": "a-forest",
            "name": "Forest",
            "asset_type_id": "at-env",
            "asset_type_name": "Environment",
            "entity_type_id": "at-env",
            "project_id": PROJECT,
            "description": None,
            "data": None,
            "preview_file_id": None,
            "canceled": False,
        },
    ]
    sequences = [{"id": "seq-1", "name": "SQ010", "project_id": PROJECT, "parent_id": None, "type": "Sequence"}]
    shots = [
        {
            "id": "s-1",
            "name": "SH010",
            "sequence_id": "seq-1",
            "sequence_name": "SQ010",
            "episode_id": None,
            "episode_name": None,
            "project_id": PROJECT,
            "frame_in": 1,
            "frame_out": 48,
            "nb_frames": 48,
            "fps": "24",
            "description": None,
            "data": {},
            "preview_file_id": "pf-sh010",
            "canceled": False,
        },
        {
            "id": "s-2",
            "name": "SH020",
            "sequence_id": "seq-1",
            "sequence_name": "SQ010",
            "episode_id": None,
            "episode_name": None,
            "project_id": PROJECT,
            "frame_in": None,
            "frame_out": None,
            "nb_frames": 72,
            "fps": None,
            "description": None,
            "data": {},
            "preview_file_id": None,
            "canceled": False,
        },
    ]

    def task(id_, entity, task_type, status, assignees, due=None, estimation=0, duration=0, **extra):
        return {
            "id": id_,
            "entity_id": entity,
            "task_type_id": task_type,
            "task_status_id": status,
            "assignees": assignees,
            "due_date": due,
            "start_date": None,
            "estimation": estimation,
            "duration": duration,
            "retake_count": 0,
            "project_id": PROJECT,
            "last_comment_date": None,
            **extra,
        }

    tasks = [
        task("t-hero-mod", "a-hero", TT_MODEL, ST_WFA, [ALICE], due="2026-10-01", estimation=960, duration=600),
        task("t-forest-mod", "a-forest", TT_MODEL, ST_WIP, [BOB], due="2026-12-01", estimation=480),
        task("t-sh010-anim", "s-1", TT_ANIM, ST_DONE, [ALICE], due="2026-09-01", estimation=480, duration=500),
        task("t-sh010-comp", "s-1", TT_COMP, ST_RETAKE, [BOB], due="2026-10-10", estimation=240, duration=60),
        task("t-sh020-anim", "s-2", TT_ANIM, ST_TODO, [], estimation=480),
    ]
    comments = {
        "t-hero-mod": [
            {
                "id": "c-2",
                "created_at": "2026-10-02T10:00:00",
                "text": "Ready for review",
                "person": {"id": ALICE, "full_name": "Alice Martin"},
                "person_id": ALICE,
                "task_status": {"id": ST_WFA, "short_name": "wfa"},
                "task_status_id": ST_WFA,
                "previews": [{"id": "pf-hero", "revision": 2}],
            },
            {
                "id": "c-1",
                "created_at": "2026-09-20T09:00:00",
                "text": "Started",
                "person": {"id": ALICE, "first_name": "Alice", "last_name": "Martin"},
                "person_id": ALICE,
                "task_status": {"id": ST_WIP, "short_name": "wip"},
                "task_status_id": ST_WIP,
                "previews": [],
            },
        ],
    }
    preview_files = {
        "pf-hero": {
            "id": "pf-hero",
            "task_id": "t-hero-mod",
            "revision": 2,
            "extension": "png",
            "original_name": "hero_v002",
            "is_movie": False,
            "status": "ready",
            "width": 1920,
            "height": 1080,
            "created_at": "2026-10-02T10:00:00",
            "validation_status": "neutral",
        },
        "pf-sh010": {
            "id": "pf-sh010",
            "task_id": "t-sh010-anim",
            "revision": 1,
            "extension": "mp4",
            "original_name": "sh010_anim_v001",
            "is_movie": True,
            "status": "ready",
            "width": 1920,
            "height": 1080,
            "created_at": "2026-08-30T10:00:00",
            "validation_status": "neutral",
        },
    }
    casting = {
        "s-1": [
            {
                "asset_id": "a-hero",
                "asset_name": "Hero",
                "asset_type_name": "Character",
                "nb_occurences": 1,
                "label": "animate",
            }
        ]
    }
    playlists = [
        {
            "id": "pl-1",
            "name": "Dailies",
            "project_id": PROJECT,
            "for_entity": "shot",
            "for_client": False,
            "task_type_id": TT_ANIM,
            "episode_id": None,
            "created_at": "2026-10-20T08:00:00",
            "updated_at": "2026-10-21T08:00:00",
            "shots": [{"entity_id": "s-1", "preview_file_id": "pf-sh010"}],
        }
    ]
    return {
        "task_types": task_types,
        "statuses": statuses,
        "people": people,
        "projects": projects,
        "asset_types": asset_types,
        "assets": assets,
        "sequences": sequences,
        "shots": shots,
        "tasks": tasks,
        "comments": comments,
        "preview_files": preview_files,
        "casting": casting,
        "playlists": playlists,
        "episodes": [],
        "me": ALICE,
    }


class FakeClient:
    """Implements the KitsuClient surface the tools use, routing GETs to the seed data."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or seed()
        self.settings = Settings(host="http://kitsu.test/api", user="u", password="p")  # type: ignore[arg-type]
        self.calls: list[tuple[str, str, Any]] = []

    # --- helpers -----------------------------------------------------------------
    def _by_id(self, kind: str) -> dict[str, dict]:
        return {r["id"]: r for r in self.data[kind]}

    def _entity(self, entity_id: str) -> dict:
        entity = {**self._by_id("assets"), **self._by_id("shots"), **self._by_id("sequences")}.get(entity_id)
        if entity is None:
            raise ToolError(f"Not found: data/entities/{entity_id}")
        return entity

    def _tasks_for(self, entity_id: str) -> list[dict]:
        return [t for t in self.data["tasks"] if t["entity_id"] == entity_id]

    def _with_tasks(self, kind: str, project_id: str | None) -> list[dict]:
        return [
            {**e, "tasks": self._tasks_for(e["id"])}
            for e in self.data[kind]
            if project_id is None or e["project_id"] == project_id
        ]

    def _task_full(self, task_id: str) -> dict:
        task = self._by_id("tasks").get(task_id)
        if task is None:
            raise ToolError(f"Not found: data/tasks/{task_id}/full")
        entity = self._entity(task["entity_id"])
        people = self._by_id("people")
        entity_type = "Shot" if task["entity_id"].startswith("s-") else entity.get("asset_type_name")
        return {
            **task,
            "project": self._by_id("projects")[task["project_id"]],
            "entity": entity,
            "entity_type": {"name": entity_type},
            "task_type": self._by_id("task_types")[task["task_type_id"]],
            "task_status": self._by_id("statuses")[task["task_status_id"]],
            "persons": [people[a] for a in task["assignees"]],
        }

    # --- KitsuClient surface ---------------------------------------------------------
    def get(self, path: str, params: dict | None = None) -> Any:
        self.calls.append(("GET", path, params))
        return copy.deepcopy(self._route(path, params or {}))

    def get_bytes(self, path: str) -> bytes:
        self.calls.append(("GET", path, None))
        return b"\x89PNG fake " + path.encode()

    def post(self, path: str, data: Any) -> Any:
        self.calls.append(("POST", path, data))
        return {"id": "new", **(data if isinstance(data, dict) else {})}

    def put(self, path: str, data: dict) -> Any:
        self.calls.append(("PUT", path, data))
        return {"id": "updated", **data}

    def user_id(self) -> str:
        return self.data["me"]

    def _person_tasks(self, person_id: str, done: bool) -> list[dict]:
        statuses = self._by_id("statuses")
        return [
            {
                "id": t["id"],
                "project_id": t["project_id"],
                "project_name": "Demo Short",
                "entity_name": self._entity(t["entity_id"])["name"],
                "entity_type_name": "Shot" if t["entity_id"].startswith("s-") else "Character",
                "sequence_name": "SQ010" if t["entity_id"].startswith("s-") else None,
                "task_type_name": self._by_id("task_types")[t["task_type_id"]]["name"],
                "task_status_short_name": statuses[t["task_status_id"]]["short_name"],
                "due_date": t["due_date"],
                "estimation": t["estimation"],
                "duration": t["duration"],
                "last_comment_date": t["last_comment_date"],
            }
            for t in self.data["tasks"]
            if person_id in t["assignees"] and statuses[t["task_status_id"]]["is_done"] == done
        ]

    def _route(self, path: str, params: dict) -> Any:  # noqa: C901 - a router is a long switch
        d = self.data
        project_id = params.get("project_id")
        simple = {
            "data/task-types": d["task_types"],
            "data/task-status": d["statuses"],
            "data/persons": d["people"],
            "data/projects": d["projects"],
            "data/projects/open": [p for p in d["projects"] if p["project_status_id"] == "ps-open"],
            "data/project-status": [{"id": "ps-open", "name": "Open"}, {"id": "ps-closed", "name": "Closed"}],
            "data/asset-types": d["asset_types"],
            "data/departments": [{"id": "dep-anim", "name": "Animation"}],
        }
        if path in simple:
            return simple[path]
        if path == "auth/authenticated":
            return {"user": self._by_id("people")[d["me"]]}
        if path == "data/assets/with-tasks":
            return self._with_tasks("assets", project_id)
        if path == "data/shots/with-tasks":
            shots = self._with_tasks("shots", project_id)
            if params.get("sequence_id"):
                shots = [s for s in shots if s["sequence_id"] == params["sequence_id"]]
            return shots
        if path == "data/assets":
            return [a for a in d["assets"] if project_id in (None, a["project_id"])]
        if path == "data/shots":
            return [s for s in d["shots"] if project_id in (None, s["project_id"])]
        if path == "data/tasks":
            return [t for t in d["tasks"] if project_id in (None, t["project_id"])]
        if path == "data/user/tasks":
            return self._person_tasks(d["me"], done=False)
        if m := re.fullmatch(r"data/persons/([^/]+)/(tasks|done-tasks)", path):
            return self._person_tasks(m[1], done=m[2] == "done-tasks")
        if m := re.fullmatch(r"data/projects/([^/]+)", path):
            project = self._by_id("projects").get(m[1])
            if project is None:
                raise ToolError(f"Not found: {path}")
            return project
        if m := re.fullmatch(r"data/projects/([^/]+)/asset-types", path):
            used = {a["asset_type_id"] for a in d["assets"] if a["project_id"] == m[1]}
            return [t for t in d["asset_types"] if t["id"] in used]
        if m := re.fullmatch(r"data/projects/([^/]+)/(sequences|episodes|playlists)", path):
            return [r for r in d[m[2]] if r["project_id"] == m[1]]
        if m := re.fullmatch(r"data/projects/([^/]+)/team", path):
            return d["people"]
        if m := re.fullmatch(r"data/projects/([^/]+)/entities/([^/]+)/casting", path):
            return d["casting"].get(m[2], [])
        if m := re.fullmatch(r"data/assets/([^/]+)/cast-in", path):
            return [
                {
                    "shot_id": sid,
                    "shot_name": self._entity(sid)["name"],
                    "sequence_name": "SQ010",
                    "episode_name": None,
                    "nb_occurences": c["nb_occurences"],
                }
                for sid, cast in d["casting"].items()
                for c in cast
                if c["asset_id"] == m[1]
            ]
        if m := re.fullmatch(r"data/(assets|shots|entities)/([^/]+)", path):
            return self._entity(m[2])
        if m := re.fullmatch(r"data/(assets|shots|entities)/([^/]+)/tasks", path):
            return self._tasks_for(m[2])
        if m := re.fullmatch(r"data/tasks/([^/]+)/full", path):
            return self._task_full(m[1])
        if m := re.fullmatch(r"data/tasks/([^/]+)/comments", path):
            return d["comments"].get(m[1], [])
        if m := re.fullmatch(r"data/tasks/([^/]+)/previews", path):
            return [p for p in d["preview_files"].values() if p["task_id"] == m[1]]
        if m := re.fullmatch(r"data/preview-files/([^/]+)", path):
            return d["preview_files"][m[1]]
        if m := re.fullmatch(r"data/playlists/([^/]+)", path):
            return self._by_id("playlists")[m[1]]
        if m := re.fullmatch(r"actions/tasks/([^/]+)/time-spents", path):
            return {"total": self._by_id("tasks")[m[1]]["duration"]}
        raise ToolError(f"Not found: {path} (no fake route)")
