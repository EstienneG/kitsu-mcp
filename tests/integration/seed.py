"""Seed a fresh Zou (the cgwire/cgwire image) with a tiny production for the integration tests.

Usage: python tests/integration/seed.py http://127.0.0.1:8090/api
Idempotent: running it twice reuses what exists.
"""

import sys

import gazu

ADMIN = ("admin@example.com", "mysecretpassword")  # the image's default admin
PROJECT = "MCP Test"


def status(short_name: str) -> dict:
    return next(s for s in gazu.task.all_task_statuses() if s["short_name"].lower() == short_name)


def main(host: str) -> None:
    gazu.set_host(host)
    gazu.log_in(*ADMIN)
    project = gazu.project.get_project_by_name(PROJECT) or gazu.project.new_project(PROJECT, production_type="tvshow")
    character = gazu.asset.get_asset_type_by_name("Character") or gazu.asset.new_asset_type("Character")
    hero = gazu.asset.get_asset_by_name(project, "Hero") or gazu.asset.new_asset(project, character, "Hero")
    episode = gazu.shot.get_episode_by_name(project, "E01") or gazu.shot.new_episode(project, "E01")
    sequence = gazu.shot.get_sequence_by_name(project, "SQ01", episode) or gazu.shot.new_sequence(
        project, "SQ01", episode=episode
    )
    shot = gazu.shot.get_shot_by_name(sequence, "SH010") or gazu.shot.new_shot(project, sequence, "SH010", nb_frames=48)
    gazu.casting.update_shot_casting(project, shot, [{"asset_id": hero["id"], "nb_occurences": 1}])

    modeling = gazu.task.get_task_type_by_name("Modeling")
    animation = gazu.task.get_task_type_by_name("Animation")
    for task_type in (modeling, animation):
        gazu.project.add_task_type(project, task_type, priority=1)
    for short_name in ("todo", "wip", "wfa", "done", "retake"):
        gazu.project.add_task_status(project, status(short_name))

    admin = gazu.client.get_current_user()
    gazu.task.get_task_by_entity(hero, modeling) or gazu.task.new_task(hero, modeling, assignees=[admin])
    anim = gazu.task.get_task_by_entity(shot, animation) or gazu.task.new_task(shot, animation, assignees=[admin])
    if not gazu.task.all_comments_for_task(anim):
        gazu.task.add_comment(anim, status("wip"), "Blocking done, starting splines")
    print(f"Seeded {PROJECT} ({project['id']})")


if __name__ == "__main__":
    main(sys.argv[1])
