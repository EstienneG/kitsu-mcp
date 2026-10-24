"""Prompt templates for common production-tracking questions."""

from kitsu_mcp.app import mcp


@mcp.prompt(tags={"reporting"})
def project_status_report(project: str) -> str:
    """Write a status report for a production."""
    return (
        f"Write a concise status report for the Kitsu project '{project}'.\n"
        f"1. Call project_overview for '{project}' and summarize overall completion and each task type's progress "
        "(omitted tasks are counted apart; mention them if there are many).\n"
        "2. Call search_tasks with overdue=True and group_by='assignee', and list the most urgent overdue tasks "
        "per person.\n"
        "3. Call workload and point out anyone overloaded and how much open work is unassigned.\n"
        "End with three concrete recommendations. Use tables where they help."
    )


@mcp.prompt(tags={"reporting"})
def review_queue(project: str) -> str:
    """List what is waiting for a supervisor's review."""
    return (
        f"Find everything waiting for review on the Kitsu project '{project}'.\n"
        "Call search_tasks with waiting_feedback=True and sort_by='last_comment_date'. Group the result by task "
        "type, oldest request first, and show for each the entity, assignee and how long it has waited. "
        "For the three oldest, call get_task and quote the artist's latest comment; when the task has a "
        "last_preview_file_id that is a video, review_video shows the frames the comments point at."
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


@mcp.prompt(tags={"video"})
def review_shot(shot_id: str, task_type: str | None = None) -> str:
    """Review a shot's latest movie against the feedback on it."""
    task = f"its {task_type} task" if task_type else "the task with the most recent comments"
    return (
        f"Review the latest movie of the shot with ID '{shot_id}' (find IDs with list_shots, or recent uploads "
        "with recent_previews).\n"
        f"1. Call get_shot to find {task} (each task lists its last_preview_file_id). Call get_video_info with "
        "that preview_file_id for the duration, fps and frame count.\n"
        "2. Call get_video_contact_sheet (n=12) on the same preview for an overview and describe what happens.\n"
        "3. Call get_task on the task to read its comments, then review_video on the task to see the frames the "
        "comments point at (timecodes, frame numbers, drawn annotations).\n"
        "4. For a closer look at a moment call get_video_frames; if the task has an earlier movie revision, "
        "compare_revisions shows what changed.\n"
        "Report, per comment: the feedback, the frames it refers to, and whether the latest movie seems to address "
        "it. Flag uncertain observations: you only see sampled still frames and cannot hear the audio."
    )
