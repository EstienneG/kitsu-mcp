"""In-memory stand-in for the Kitsu API, seeded with a small invented production."""

import copy
import re
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from kitsu_mcp.client import NotFoundError, size_guard
from kitsu_mcp.config import Settings

PROJECT = "p-1"
TT_MODEL, TT_ANIM, TT_COMP = "tt-model", "tt-anim", "tt-comp"
ST_WIP, ST_WFA, ST_DONE, ST_RETAKE, ST_TODO = "st-wip", "st-wfa", "st-done", "st-retake", "st-todo"
ALICE, BOB = "person-alice", "person-bob"


def seed() -> dict[str, Any]:
    task_types = [
        {"id": TT_MODEL, "name": "Modeling", "short_name": "MOD", "for_entity": "Asset", "department_id": "dep-model"},
        {"id": TT_ANIM, "name": "Animation", "short_name": "ANIM", "for_entity": "Shot", "department_id": "dep-anim"},
        {"id": TT_COMP, "name": "Compositing", "short_name": "COMP", "for_entity": "Shot", "department_id": "dep-comp"},
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
            "data": {"rigged": "true", "date_rendu": "2026-11-06", "resolution": ""},
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
            "parent_id": "seq-1",
            "sequence_name": "SQ010",
            "episode_id": None,
            "episode_name": None,
            "project_id": PROJECT,
            "frame_in": 1,
            "frame_out": 48,
            "nb_frames": 48,
            "fps": "24",
            "description": None,
            "data": {"anim_level": "⭐⭐", "key_shot": "true", "handle_in": 4},
            "preview_file_id": "pf-sh010",
            "canceled": False,
        },
        {
            "id": "s-2",
            "name": "SH020",
            "sequence_id": "seq-1",
            "parent_id": "seq-1",
            "sequence_name": "SQ010",
            "episode_id": None,
            "episode_name": None,
            "project_id": PROJECT,
            "frame_in": None,
            "frame_out": None,
            "nb_frames": 72,
            "fps": None,
            "description": None,
            "data": {"frame_in": "101", "frame_out": 172, "key_shot": "false"},
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
        "t-sh010-anim": [
            {
                "id": "c-anim-3",
                "created_at": "2026-08-31T09:00:00",
                "text": "Approved, the v1 00:00:01:12 (37) fix works.",
                "person": {"id": BOB, "full_name": "Bob Leroy"},
                "person_id": BOB,
                "task_status": {"id": ST_DONE, "short_name": "done"},
                "task_status_id": ST_DONE,
                "previews": [],
            },
            {
                "id": "c-anim-2",
                "created_at": "2026-08-30T10:00:00",
                "text": "v2: fixed the arm at frame 30",
                "person": {"id": ALICE, "full_name": "Alice Martin"},
                "person_id": ALICE,
                "task_status": {"id": ST_WFA, "short_name": "wfa"},
                "task_status_id": ST_WFA,
                "previews": [{"id": "pf-sh010", "revision": 2}],
            },
            {
                "id": "c-anim-1",
                "created_at": "2026-08-20T10:00:00",
                "text": "Arm pops at 00:00:01:00 and again around 2.5s; see drawing.",
                "person": {"id": BOB, "full_name": "Bob Leroy"},
                "person_id": BOB,
                "task_status": {"id": ST_RETAKE, "short_name": "retake"},
                "task_status_id": ST_RETAKE,
                "previews": [{"id": "pf-sh010-v1", "revision": 1}],
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
            "revision": 2,
            "extension": "mp4",
            "original_name": "sh010_anim_v002",
            "is_movie": True,
            "status": "ready",
            "width": 1920,
            "height": 1080,
            "duration": 3.0,
            "position": 1,
            "file_size": 9000,
            "annotations": None,
            "data": {"original_file_size": 4000},
            "created_at": "2026-08-30T10:00:00",
            "validation_status": "neutral",
        },
        "pf-sh010-v2b": {
            "id": "pf-sh010-v2b",
            "task_id": "t-sh010-anim",
            "revision": 2,
            "position": 2,
            "extension": "mp4",
            "original_name": "sh010_anim_v002_render",
            "is_movie": False,
            "status": "ready",
            "width": 1920,
            "height": 1080,
            "duration": 3.0,
            "file_size": 9500,
            "annotations": None,
            "data": {},
            "created_at": "2026-08-30T10:05:00",
            "validation_status": "neutral",
        },
        "pf-sh010-broken": {
            "id": "pf-sh010-broken",
            "task_id": "t-sh010-anim",
            "revision": 3,
            "position": 1,
            "extension": "mp4",
            "original_name": "sh010_anim_v003",
            "is_movie": False,
            "status": "broken",
            "width": 0,
            "height": 0,
            "duration": 0,
            "file_size": 0,
            "annotations": None,
            "data": {},
            "created_at": "2026-09-01T10:00:00",
            "validation_status": "neutral",
        },
        "pf-sh010-v1": {
            "id": "pf-sh010-v1",
            "task_id": "t-sh010-anim",
            "revision": 1,
            "extension": "mov",
            "original_name": "sh010_anim_v001",
            "is_movie": False,  # Kitsu's flag is unreliable: the extension says it is a movie
            "status": "ready",
            "width": 1920,
            "height": 1080,
            "duration": 2.0,
            # Kitsu stores drawings by time; 1.0 s at 24 fps is frame 25, 2.0 s would be past the end.
            "annotations": [
                {"time": 1.0, "drawing": {"objects": [{"type": "path"}]}},
                {"time": 0.5, "drawing": {"objects": []}},
            ],
            "data": {},
            "created_at": "2026-08-20T10:00:00",
            "validation_status": "rejected",
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
    # Custom fields ("metadata descriptors"), shaped like the live instance's. Kitsu stores values as text.
    custom_fields = [
        {
            "id": "md-level",
            "project_id": PROJECT,
            "name": "Anim Level",
            "field_name": "anim_level",
            "entity_type": "Shot",
            "data_type": "list",
            "choices": ["⭐", "⭐⭐", "⭐⭐⭐"],
            "departments": ["dep-anim"],
            "position": 2,
            "for_client": False,
        },
        {
            "id": "md-key",
            "project_id": PROJECT,
            "name": "key_shot",
            "field_name": "key_shot",
            "entity_type": "Shot",
            "data_type": "boolean",
            "choices": [],
            "departments": [],
            "position": 1,
            "for_client": False,
        },
        {
            "id": "md-rigged",
            "project_id": PROJECT,
            "name": "Rigged",
            "field_name": "rigged",
            "entity_type": "Asset",
            "data_type": "boolean",
            "choices": [],
            "departments": [],
            "position": None,
            "for_client": True,
        },
        {
            "id": "md-due",
            "project_id": PROJECT,
            "name": "DATE RENDU",
            "field_name": "date_rendu",
            "entity_type": "Asset",
            "data_type": "date",
            "choices": [],
            "departments": [],
            "position": None,
            "for_client": False,
        },
    ]
    departments = [
        {"id": "dep-model", "name": "Modeling", "color": "#888", "archived": False},
        {"id": "dep-anim", "name": "Animation", "color": "#888", "archived": False},
        {"id": "dep-comp", "name": "Compositing", "color": "#888", "archived": False},
        {"id": "dep-sound", "name": "Sound", "color": "#888", "archived": False},
    ]
    return {
        "departments": departments,
        "custom_fields": custom_fields,
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
        "edits": [{"id": "ed-trailer", "name": "Trailer Cut", "project_id": "p-1"}],
        "concepts": [{"id": "co-hero", "name": "Hero sketch v2", "project_id": "p-1"}],
        "notifications": [
            {
                "id": "n-1",
                "notification_type": "comment",
                "read": False,
                "created_at": "2026-10-14T09:00:00",
                "project_id": "p-1",
                "project_name": "Demo Short",
                "full_entity_name": "SQ010 / SH010",
                "task_id": "t-sh010-comp",
                "task_type_id": TT_COMP,
                "task_status_id": ST_RETAKE,
                "author_id": BOB,
                "comment_id": "c-comp-1",
                "comment_text": "Edges flicker, please fix",
                "reply_text": "",
            },
            {
                "id": "n-0",
                "notification_type": "assignation",
                "read": True,
                "created_at": "2026-10-01T09:00:00",
                "project_id": "p-1",
                "project_name": "Demo Short",
                "full_entity_name": "Hero",
                "task_id": "t-hero-mod",
                "task_type_id": TT_MODEL,
                "task_status_id": ST_WIP,
                "author_id": BOB,
                "comment_id": None,
                "comment_text": "",
                "reply_text": "",
            },
        ],
        "time_spents": [
            # Past days only: write tests log time on 2026-10-14 and expect an empty day.
            {"task_id": "t-hero-mod", "person_id": ALICE, "date": "2026-10-12", "duration": 240},
            {"task_id": "t-hero-mod", "person_id": ALICE, "date": "2026-10-13", "duration": 180},
            {"task_id": "t-sh010-anim", "person_id": ALICE, "date": "2026-10-13", "duration": 60},
            {"task_id": "t-sh010-anim", "person_id": ALICE, "date": "2026-09-01", "duration": 500},
            {"task_id": "t-forest-mod", "person_id": BOB, "date": "2026-10-13", "duration": 120},
        ],
        "me": ALICE,
        "day_offs": [
            {"id": "do-1", "person_id": ALICE, "date": "2026-10-09", "end_date": "2026-10-12", "description": "Trip"},
            {"id": "do-2", "person_id": ALICE, "date": "2026-08-03", "end_date": "2026-08-14", "description": None},
        ],
        "schedule_items": [
            # Task-type spans (no object_id): Modeling ended before today (2026-10-15) with work still open.
            {
                "id": "si-mod",
                "task_type_id": TT_MODEL,
                "object_id": None,
                "start_date": "2026-02-01",
                "end_date": "2026-09-30",
                "man_days": 40,
            },
            {
                "id": "si-anim",
                "task_type_id": TT_ANIM,
                "object_id": None,
                "start_date": "2026-06-01",
                "end_date": "2026-11-30",
                "man_days": None,
            },
            # A per-shot item (object_id set) is not a task-type span.
            {
                "id": "si-sh010",
                "task_type_id": TT_ANIM,
                "object_id": "s-1",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "man_days": None,
            },
        ],
        "milestones": [
            {"id": "ms-2", "date": "2026-12-01", "name": "Delivery", "task_type_id": None},
            {"id": "ms-1", "date": "2026-11-01", "name": "Anim lock", "task_type_id": TT_ANIM},
        ],
        # Zou's quotas answer: person -> period -> measure -> {key: value}; weeks are unpadded ("2026-7").
        "quotas": {
            ALICE: {
                "week": {
                    "count": {"2026-7": 1.0, "2026-40": 2.0, "2026-41": 0},
                    "frames": {"2026-7": 0, "2026-40": 96, "2026-41": 0},
                    "seconds": {"2026-7": 0, "2026-40": 4.0, "2026-41": 0},
                    "drawings": {},
                },
                "month": {"count": {"2026-02": 1.0, "2026-10": 2.0}, "frames": {"2026-10": 96}},
            },
            BOB: {"week": {"count": {"2026-40": 0}, "frames": {}}},
            # Zou sums everyone under "total".
            "total": {"week": {"count": {"2026-7": 1.0, "2026-40": 2.0}, "frames": {"2026-40": 96}}},
        },
        "budgets": [
            {"id": "b-1", "project_id": PROJECT, "name": "First pass", "revision": 1, "currency": "EUR"},
            {"id": "b-2", "project_id": PROJECT, "name": "Revised", "revision": 2, "currency": "EUR"},
        ],
        "budget_entries": {
            "b-2": [
                # 3 months at 100/day (20 days a month), October set by hand to 500.
                {
                    "id": "be-1",
                    "person_id": ALICE,
                    "department_id": "dep-anim",
                    "position": "artist",
                    "seniority": "mid",
                    "start_date": "2026-09-01",
                    "months_duration": 3,
                    "daily_salary": 100,
                    "exceptions": {"2026-10": 500, "2027-05": 9999},
                },
                {
                    "id": "be-2",
                    "person_id": BOB,
                    "department_id": "dep-model",
                    "position": "supervisor",
                    "seniority": "senior",
                    "start_date": "2026-11-01",
                    "months_duration": 1,
                    "daily_salary": 200,
                    "exceptions": {},
                },
            ],
        },
    }


class FakeClient:
    """Implements the KitsuClient surface the tools use, routing GETs to the seed data."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or seed()
        self.settings = Settings(host="http://kitsu.test/api", user="u", password="p")  # type: ignore[arg-type]
        self.credentials = None
        self.calls: list[tuple[str, str, Any]] = []
        self.movies: dict[str, bytes] = {}
        """Movie files by route (e.g. movies/low/preview-files/<id>.mp4), served by download()."""

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

    def download(self, path: str, dest: Path, max_bytes: int | None = None) -> int:
        """Serve `movies` (route → bytes), honouring the size cap like the real client."""
        self.calls.append(("GET", path, None))
        if path not in self.movies:
            raise NotFoundError(f"Not found: {path} (wrong ID, or the route does not exist)")
        data = self.movies[path]
        with dest.open("wb") as target:
            for start in range(0, len(data), 8192):
                target.write(data[start : start + 8192])
                size_guard(path, max_bytes)(min(start + 8192, len(data)), 0)
        return len(data)

    def post(self, path: str, data: Any) -> Any:
        """Apply the writes the tools send, the way Zou does, so tests see their effect."""
        self.calls.append(("POST", path, data))
        if m := re.fullmatch(r"actions/tasks/([^/]+)/comment", path):
            task = self._task_or_404(m[1], path)
            status = self._by_id("statuses")[data["task_status_id"]]
            task["task_status_id"] = status["id"]
            author = self._by_id("people")[self.data["me"]]
            new = {
                "id": f"c-{len(self.calls)}",
                "created_at": "2026-10-15T12:00:00",
                "text": data["comment"],
                "person": author,
                "person_id": author["id"],
                "task_status": status,
                "task_status_id": status["id"],
                "previews": [],
            }
            self.data["comments"].setdefault(task["id"], []).insert(0, new)
            return new
        if m := re.fullmatch(r"data/tasks/([^/]+)/comments/([^/]+)/(reply|ack)", path):
            self._task_or_404(m[1], path)
            target = next((c for c in self.data["comments"].get(m[1], []) if c["id"] == m[2]), None)
            if target is None:
                raise ToolError(f"Not found: {path}")
            if m[3] == "reply":
                reply = {
                    "id": f"r-{len(self.calls)}",
                    "created_at": "2026-10-15T12:00:00",
                    "text": data["text"],
                    "person": self._by_id("people")[self.data["me"]],
                }
                target.setdefault("replies", []).append(reply)
                return reply
            # Zou toggles the acknowledgement.
            acks = target.setdefault("acknowledgements", [])
            acks.remove(self.data["me"]) if self.data["me"] in acks else acks.append(self.data["me"])
            return target
        if path == "data/playlists/":
            playlist = {
                "id": f"pl-new-{len(self.calls)}",
                "task_type_id": None,
                "episode_id": None,
                "created_at": "2026-10-15T12:00:00",
                "updated_at": "2026-10-15T12:00:00",
                **data,
                "shots": [],
            }
            self.data["playlists"].append(playlist)
            return playlist
        if m := re.fullmatch(r"actions/playlists/([^/]+)/add-entity", path):
            # Zou appends the entry as given, even when the entity is already in the playlist.
            playlist = self._by_id("playlists").get(m[1])
            if playlist is None:
                raise ToolError(f"Not found: {path}")
            playlist["shots"].append({"entity_id": data["entity_id"], "preview_file_id": data.get("preview_file_id")})
            return playlist
        if m := re.fullmatch(r"actions/tasks/([^/]+)/time-spents/([^/]+)/persons/([^/]+)/add", path):
            task = self._task_or_404(m[1], path)
            task["duration"] = (task["duration"] or 0) + data["duration"]
            entry = {"task_id": task["id"], "person_id": m[3], "date": m[2], "duration": data["duration"]}
            self.data.setdefault("time_spents", []).append(entry)
            return entry
        raise ToolError(f"Not found: {path} (no fake route)")

    def put(self, path: str, data: dict) -> Any:
        self.calls.append(("PUT", path, data))
        if m := re.fullmatch(r"actions/persons/([^/]+)/assign", path):
            for task_id in data["task_ids"]:
                task = self._task_or_404(task_id, path)
                if m[1] not in task["assignees"]:
                    task["assignees"].append(m[1])
            return [self._by_id("tasks")[t] for t in data["task_ids"]]
        if m := re.fullmatch(r"data/tasks/([^/]+)", path):
            task = self._task_or_404(m[1], path)
            task.update(data)
            return task
        if path == "actions/tasks/clear-assignation":
            # Zou answers with the tasks it changed, silently skipping those the caller may not unassign.
            changed = []
            for task_id in data["task_ids"]:
                task = self._task_or_404(task_id, path)
                if task_id in self.data.get("unassign_denied", ()):
                    continue
                task["assignees"] = [a for a in task["assignees"] if a != data.get("person_id")]
                changed.append(task_id)
            return changed
        raise ToolError(f"Not found: {path} (no fake route)")

    def _task_or_404(self, task_id: str, path: str) -> dict:
        task = self._by_id("tasks").get(task_id)
        if task is None:
            raise ToolError(f"Not found: {path}")
        return task

    def user_id(self) -> str:
        return self.data["me"]

    def _news(self, project_id: str, params: dict) -> dict:
        """Zou's activity feed: one item per comment, newest first, paged; filters as Zou applies them."""
        tasks = self._by_id("tasks")
        items = []
        for task_id, comments in self.data["comments"].items():
            task = tasks.get(task_id)
            if task is None or task["project_id"] != project_id:
                continue
            for c in comments:
                preview = (c.get("previews") or [{}])[0]
                record = self.data["preview_files"].get(preview.get("id"), {})
                entity = self._entity(task["entity_id"])
                items.append(
                    {
                        "created_at": c["created_at"],
                        "comment_id": c["id"],
                        "change": c.get("change", True),
                        "task_id": task_id,
                        "task_type_id": task["task_type_id"],
                        "task_status_id": c.get("task_status_id"),
                        "author_id": c.get("person_id"),
                        "task_entity_id": task["entity_id"],
                        "full_entity_name": f"{entity.get('sequence_name')} / {entity['name']}"
                        if entity.get("sequence_name")
                        else entity["name"],
                        "preview_file_id": preview.get("id"),
                        "preview_file_revision": preview.get("revision"),
                        "preview_file_extension": record.get("extension"),
                    }
                )
        if params.get("only_preview") == "true":
            items = [i for i in items if i["preview_file_id"]]
        if params.get("task_type_id"):
            items = [i for i in items if i["task_type_id"] == params["task_type_id"]]
        if params.get("after"):
            items = [i for i in items if i["created_at"] > params["after"]]
        items.sort(key=lambda i: i["created_at"], reverse=True)
        limit, page = int(params.get("limit", 50)), int(params.get("page", 1))
        return {
            "data": items[(page - 1) * limit : page * limit],
            "total": len(items),
            "nb_pages": max(1, -(-len(items) // limit)),
            "page": page,
            "limit": limit,
        }

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
                "task_status_id": t["task_status_id"],
                "task_status_short_name": statuses[t["task_status_id"]]["short_name"],
                "due_date": t["due_date"],
                "estimation": t["estimation"],
                "duration": t["duration"],
                "last_comment_date": t["last_comment_date"],
            }
            for t in self.data["tasks"]
            # Zou splits the two routes by Kitsu's own done flag, not by what the status means.
            if person_id in t["assignees"] and bool(statuses[t["task_status_id"]].get("is_done")) == done
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
            "data/departments": d["departments"],
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
        if m := re.fullmatch(r"data/projects/([^/]+)/news", path):
            return self._news(m[1], params)
        if m := re.fullmatch(r"data/projects/([^/]+)/playlists", path):
            # Zou pages playlists 20 at a time; past the end it returns an empty page.
            page = int(params.get("page", 1))
            playlists = [r for r in d["playlists"] if r["project_id"] == m[1]]
            return playlists[(page - 1) * 20 : page * 20]
        if m := re.fullmatch(r"data/projects/([^/]+)/(sequences|episodes|edits|concepts)", path):
            return [r for r in d.get(m[2], []) if r["project_id"] == m[1]]
        if path == "data/user/notifications":
            return d.get("notifications", [])
        if m := re.fullmatch(r"data/persons/([^/]+)/time-spents", path):
            start, end = params["start_date"], params["end_date"]
            return [e for e in d.get("time_spents", []) if e["person_id"] == m[1] and start <= e["date"] <= end]
        if m := re.fullmatch(r"data/projects/([^/]+)/metadata-descriptors", path):
            return [f for f in d["custom_fields"] if f["project_id"] == m[1]]
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
            # Zou: {"total": minutes, "<person id>": [entries], ...}
            spent: dict[str, Any] = {"total": self._by_id("tasks")[m[1]]["duration"]}
            for entry in d.get("time_spents", []):
                if entry["task_id"] == m[1]:
                    spent.setdefault(entry["person_id"], []).append(entry)
            return spent
        if m := re.fullmatch(r"data/persons/([^/]+)/day-offs", path):
            if m[1] in d.get("day_offs_denied", ()):
                raise ToolError(f"Permission denied for GET {path}")
            return [o for o in d.get("day_offs", []) if o["person_id"] == m[1]]
        if path == "data/schedule-items/":
            raise ToolError(f"Permission denied for GET {path}")  # Zou: admins only; tools must not need it
        if m := re.fullmatch(r"data/projects/([^/]+)/schedule-items", path):
            return d.get("schedule_items", []) if m[1] == PROJECT else []
        if re.fullmatch(r"data/projects/([^/]+)/schedule-items/task-types", path):
            raise AssertionError("schedule-items/task-types creates missing items in Zou: never read it")
        if m := re.fullmatch(r"data/projects/([^/]+)/milestones", path):
            return d.get("milestones", []) if m[1] == PROJECT else []
        if m := re.fullmatch(r"data/projects/([^/]+)/quotas/([^/]+)", path):
            if params.get("count_mode") not in ("weighted", "weighteddone", "feedback", "done"):
                raise ToolError("count_mode must be equal to weighted, weigtheddone, feedback, or done")
            return d.get("quotas", {}) if m[2] == TT_ANIM else {}
        if m := re.fullmatch(r"data/projects/([^/]+)/budgets", path):
            return [b for b in d.get("budgets", []) if b["project_id"] == m[1]]
        if m := re.fullmatch(r"data/projects/([^/]+)/budgets/([^/]+)/entries", path):
            return d.get("budget_entries", {}).get(m[2], [])
        raise ToolError(f"Not found: {path} (no fake route)")
