"""Argument checks shared by tools."""

import re
from datetime import date
from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field

# Kitsu IDs are UUIDs. Anything else (a name like "SH100", "not-a-uuid") makes Zou answer 500, not 404.
UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
id_pattern = UUID
"""What object_id accepts; the test suite widens it to the fake data's readable IDs."""

MAX_LIMIT = 500

Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT, description=f"Page size, 1-{MAX_LIMIT}")]
Offset = Annotated[int, Field(ge=0, description="Rows to skip, for paging")]


def iso_date(value: str, field: str) -> str:
    """Normalize a YYYY-MM-DD date or raise a ToolError naming the argument."""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ToolError(f"{field} must be a YYYY-MM-DD date, got '{value}'") from error


def object_id(value: str, kind: str, finder: str) -> str:
    """Check that `value` looks like a Kitsu ID; names get a pointer to the tool that finds the ID.

    kind: what the ID is for ("task", "shot", ...). finder: the tool that lists them ("search_tasks").
    """
    if not isinstance(value, str) or not id_pattern.fullmatch(value.strip()):
        article = "an" if kind[:1].lower() in "aeiou" else "a"
        raise ToolError(
            f"{value!r} is not {article} {kind} ID (Kitsu IDs look like 'a1b2c3d4-...'); use {finder} to find it"
        )
    return value.strip()
