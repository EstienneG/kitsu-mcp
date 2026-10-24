"""Argument checks shared by tools."""

from datetime import date

from fastmcp.exceptions import ToolError


def iso_date(value: str, field: str) -> str:
    """Normalize a YYYY-MM-DD date or raise a ToolError naming the argument."""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ToolError(f"{field} must be a YYYY-MM-DD date, got '{value}'") from error
