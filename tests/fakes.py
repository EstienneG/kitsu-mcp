"""In-memory stand-in for the Kitsu API, serving the invented production in tests/fake_data.py."""

import copy
import re
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from kitsu_mcp.config import Settings
from kitsu_mcp.kitsu.client import NotFoundError, size_guard
from tests.fake_data import PROJECT, TT_ANIM, seed


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
        entity = entity or self._entity_any(entity_id)
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
        if created := self._create(path, data):
            return created
        raise ToolError(f"Not found: {path} (no fake route)")

    # --- structure writes, as the dev Zou does them (checked on Zou 1.0.97) -----------------------------
    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-new-{len(self.calls)}"

    def _create(self, path: str, data: dict) -> dict | None:
        d = self.data
        if path == "data/projects":
            project = {**data, "id": self._new_id("p"), "project_status_id": "ps-open"}
            d["projects"].append(project)
            if data.get("production_type") == "tvshow":  # Zou adds a first episode to every TV show
                d["episodes"].append({"id": self._new_id("ep"), "name": "E01", "project_id": project["id"]})
            return project
        if m := re.fullmatch(r"data/projects/([^/]+)/(episodes|sequences|shots|concepts|edits)", path):
            kind = m[2]
            record = {"id": self._new_id(kind[:2]), "project_id": m[1], "canceled": False, "data": {}, **data}
            if kind == "sequences":
                record["parent_id"] = data.get("episode_id")
            if kind == "shots":
                record["parent_id"] = data["sequence_id"]
            d.setdefault(kind, []).append(record)
            return record
        if m := re.fullmatch(r"data/projects/([^/]+)/asset-types/([^/]+)/assets/new", path):
            asset = {"id": self._new_id("a"), "project_id": m[1], "entity_type_id": m[2], "canceled": False, **data}
            d["assets"].append(asset)
            return asset
        if path == "data/tasks":
            task = {"id": self._new_id("t"), "duration": 0, "estimation": None, "due_date": None, **data}
            d["tasks"].append(task)
            return task
        if m := re.fullmatch(r"actions/tasks/([^/]+)/comments/([^/]+)/add-preview", path):
            task = self._task_or_404(m[1], path)
            revision = (
                max((p.get("revision") or 0 for p in d["preview_files"].values() if p["task_id"] == m[1]), default=0)
                + 1
            )
            preview = {
                "id": self._new_id("pf"),
                "task_id": task["id"],
                "revision": revision,
                "status": "processing",
                "extension": None,
                "comment_id": m[2],
            }
            d["preview_files"][preview["id"]] = preview
            comment = next(c for c in d["comments"].get(m[1], []) if c["id"] == m[2])
            comment.setdefault("previews", []).append(preview)
            return preview
        if m := re.fullmatch(r"actions/projects/([^/]+)/delete-tasks", path):
            assert isinstance(data, list), "Zou wants a bare JSON array of task IDs"
            ids = [t for t in data if any(x["id"] == t and x["project_id"] == m[1] for x in d["tasks"])]
            d["tasks"] = [t for t in d["tasks"] if t["id"] not in ids]
            return ids
        return None

    def upload(self, path: str, file_path: str, data: dict | None = None) -> Any:
        self.calls.append(("UPLOAD", path, {"file": file_path, **(data or {})}))
        if m := re.fullmatch(r"pictures/preview-files/([^/]+)", path):
            preview = self.data["preview_files"][m[1]]
            preview.update(
                status="ready", extension=Path(file_path).suffix.lstrip(".").lower(), original_name=Path(file_path).stem
            )
            return preview
        raise ToolError(f"Not found: {path} (no fake route)")

    def _entity_any(self, entity_id: str) -> dict | None:
        for kind in ("projects", "assets", "shots", "sequences", "episodes", "concepts", "edits"):
            for record in self.data.get(kind, []):
                if record["id"] == entity_id:
                    return record
        return None

    def delete(self, path: str, params: dict | None = None) -> Any:
        self.calls.append(("DELETE", path, params or {}))
        force = bool((params or {}).get("force"))
        d = self.data
        if m := re.fullmatch(r"data/tasks/([^/]+)", path):
            self._task_or_404(m[1], path)
            d["tasks"] = [t for t in d["tasks"] if t["id"] != m[1]]
            return ""
        if m := re.fullmatch(r"data/comments/([^/]+)", path):
            for task_id, comments in d["comments"].items():
                if any(c["id"] == m[1] for c in comments):
                    d["comments"][task_id] = [c for c in comments if c["id"] != m[1]]
                    # Zou deletes the comment's previews with it
                    d["preview_files"] = {k: v for k, v in d["preview_files"].items() if v.get("comment_id") != m[1]}
                    return ""
            raise NotFoundError(f"Not found: {path}")
        if m := re.fullmatch(r"data/tasks/([^/]+)/comments/([^/]+)/reply/([^/]+)", path):
            comment = next((c for c in d["comments"].get(m[1], []) if c["id"] == m[2]), None)
            if comment is None:
                raise NotFoundError(f"Not found: {path}")
            comment["replies"] = [r for r in comment.get("replies") or [] if r.get("id") != m[3]]
            return ""
        if m := re.fullmatch(r"data/projects/([^/]+)", path):
            project = self._by_id("projects").get(m[1])
            if project is None:
                raise NotFoundError(f"Not found: {path}")
            if project["project_status_id"] != "ps-closed":
                raise ToolError(f"Kitsu rejected DELETE {path}: Only closed projects can be deleted")
            d["projects"] = [p for p in d["projects"] if p["id"] != m[1]]
            return ""
        if m := re.fullmatch(r"data/(assets|shots|concepts|edits|sequences|episodes)/([^/]+)", path):
            kind, record_id = m[1], m[2]
            if not any(r["id"] == record_id for r in d.get(kind, [])):
                raise NotFoundError(f"Not found: {path}")
            if kind in ("assets", "shots", "concepts", "edits"):
                has_tasks = any(t["entity_id"] == record_id for t in d["tasks"])
                if has_tasks and not force:  # Zou cancels instead of deleting
                    next(r for r in d[kind] if r["id"] == record_id)["canceled"] = True
                    return ""
                d["tasks"] = [t for t in d["tasks"] if t["entity_id"] != record_id]
            d[kind] = [r for r in d[kind] if r["id"] != record_id]
            return ""
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
        if m := re.fullmatch(r"data/comments/([^/]+)", path):
            for comments in self.data["comments"].values():
                for comment in comments:
                    if comment["id"] == m[1]:
                        comment.update(data)
                        return comment
            raise NotFoundError(f"Not found: {path}")
        if m := re.fullmatch(r"actions/preview-files/([^/]+)/set-main-preview", path):
            preview = self.data["preview_files"][m[1]]
            task = self._task_or_404(preview["task_id"], path)
            self._entity(task["entity_id"])["preview_file_id"] = preview["id"]
            return preview
        if m := re.fullmatch(r"data/(entities|projects|shots)/([^/]+)", path):
            record = self._entity_any(m[2])
            if record is None:
                raise NotFoundError(f"Not found: {path}")
            if "data" in data:  # Zou merges custom fields
                record["data"] = {**(record.get("data") or {}), **data["data"]}
            record.update({k: v for k, v in data.items() if k != "data"})
            return record
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
        if m := re.fullmatch(r"data/(sequences|episodes|concepts|edits)/([^/]+)", path):
            if (record := self._entity_any(m[2])) is None:
                raise NotFoundError(f"Not found: {path}")
            return record
        if m := re.fullmatch(r"data/(concepts|edits)/([^/]+)/tasks", path):
            return self._tasks_for(m[2])
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
