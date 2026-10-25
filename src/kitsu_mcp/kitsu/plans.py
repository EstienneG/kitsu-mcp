"""Write plans: what a write tool will send, worked out with reads only, then previewed or sent.

Every write tool builds a `Plan` first (resolve names, read the current state, run the checks). With
dry_run=True the tool returns `plan.preview()` and nothing is sent; otherwise it calls `plan.send()`, which
sends exactly the planned requests. One code path builds both, so a preview never differs from the real call.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.models import DryRunResult, PlannedRequest

# Kitsu roles. Kitsu usually lets artists ("user") and vendors set only statuses flagged is_artist_allowed, clients
# only those flagged is_client_allowed, and keeps assigning, scheduling and logging time for others to leads.
# Studios and Zou versions differ, so the tools warn about these rather than refuse.
ARTIST_ROLES = frozenset({"user", "vendor"})
LEAD_ROLES = frozenset({"admin", "manager", "supervisor"})


class PartialSendError(ToolError):
    """A request failed after earlier ones of the same plan were sent: those changes are in Kitsu."""

    def __init__(self, sent: int, total: int, cause: Exception) -> None:
        super().__init__(f"Sent {sent} of {total} requests, then failed: {str(cause).rstrip('.')}.")
        self.sent = sent
        self.cause = cause


@dataclass
class Plan:
    tool: str
    would: str
    """The action in one line, e.g. "Change Hero / Modeling from wfa to done"."""
    message: str = ""
    """What the real call reports once sent."""
    requests: list[PlannedRequest] = field(default_factory=list)
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failure: str | None = None
    """A failed check: the dry run reports would_fail, the real call refuses with this reason."""

    def request(
        self, method: Literal["POST", "PUT", "DELETE", "UPLOAD"], path: str, payload: dict[str, Any] | None = None
    ) -> None:
        """UPLOAD sends payload["file"] (a local path) as a multipart file, with the rest as form data."""
        self.requests.append(PlannedRequest(method=method, path=path, payload=payload or {}))

    def fail(self, reason: str) -> None:
        """Record a failed check; the first one is the reason given."""
        self.failure = self.failure or reason

    def preview(self) -> DryRunResult:
        """The dry-run answer. Appended to KITSU_DRY_RUN_LOG when that is set."""
        result = DryRunResult(
            ok=self.failure is None,
            verdict="would_fail" if self.failure else "would_succeed",
            would=self.would,
            reason=self.failure,
            requests=self.requests,
            before=self.before,
            after=self.after,
            warnings=self.warnings,
        )
        _log(self.tool, result)
        return result

    def send(self) -> list[Any]:
        """Send the planned requests in order (or refuse, if a check failed); returns Kitsu's answers."""
        if self.failure:
            raise ToolError(f"{self.failure} Nothing was sent.")
        client = get_client()
        answers = []
        for done, req in enumerate(self.requests):
            try:
                answers.append(_send(client, req))
            except Exception as error:
                if not done:
                    raise
                raise PartialSendError(done, len(self.requests), error) from error
        return answers


def _send(client, req: PlannedRequest) -> Any:
    if req.method == "POST":
        return client.post(req.path, req.payload)
    if req.method == "PUT":
        return client.put(req.path, req.payload)
    if req.method == "DELETE":
        return client.delete(req.path, req.payload or None)
    data = {k: v for k, v in req.payload.items() if k != "file"}
    return client.upload(req.path, req.payload["file"], data or None)


def current_user() -> dict:
    """The logged-in Kitsu user (id, full_name, role)."""
    return get_client().get("auth/authenticated")["user"]


def _log(tool: str, result: DryRunResult) -> None:
    path = get_client().settings.dry_run_log
    if path is None:
        return
    line = {"time": datetime.now().isoformat(timespec="seconds"), "tool": tool, **result.model_dump()}
    try:
        with path.expanduser().open("a", encoding="utf-8") as log:
            log.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except OSError as error:
        result.warnings.append(f"Could not append to KITSU_DRY_RUN_LOG: {error}")
