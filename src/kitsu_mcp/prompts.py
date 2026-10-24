"""Prompt templates for common production-tracking questions."""

from kitsu_mcp.app import mcp


@mcp.prompt(tags={"reporting"})
def project_status_report(project: str) -> str:
    """Write a status report for a production."""
    return (
        f"Write a concise status report for the Kitsu project '{project}'.\n"
        f"1. Call project_overview for '{project}' and summarize overall completion and each task type's progress.\n"
        "2. Call search_tasks with overdue=True and list the most urgent overdue tasks (entity, task type, "
        "assignee, due date).\n"
        "3. Call workload and point out anyone overloaded and how much open work is unassigned.\n"
        "End with three concrete recommendations. Use tables where they help."
    )


@mcp.prompt(tags={"reporting"})
def review_queue(project: str) -> str:
    """List what is waiting for a supervisor's review."""
    return (
        f"Find everything waiting for review on the Kitsu project '{project}'.\n"
        "Call list_task_statuses and pick the statuses whose is_feedback_request flag is true. Then call "
        "search_tasks with those statuses, include_done=False and sort_by='last_comment_date'. Group the result by "
        "task type, oldest request first, and show for each the entity, assignee and how long it has waited. "
        "For the three oldest, call get_task and quote the artist's latest comment."
    )


@mcp.prompt(tags={"tasks"})
def my_day() -> str:
    """Plan the logged-in artist's day."""
    return (
        "Call my_tasks, then get_task on each task that is in retake or has a due date within the next week. "
        "Summarize what changed (latest supervisor comments), and propose an order to work in, most urgent first, "
        "with one line of reasoning per task."
    )


@mcp.prompt(tags={"people"})
def person_summary(person: str, project: str | None = None) -> str:
    """Summarize one person's current work."""
    scope = f" on project '{project}'" if project else ""
    return (
        f"Summarize what {person} is working on{scope}. Call get_person_tasks (and with done=True for recent "
        "completions). Report open tasks by status, anything overdue or in retake, estimate vs. time logged, "
        "and what they finished recently."
    )
