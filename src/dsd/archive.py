"""Archive and restore projects, like Pane archives a pane.

Archiving hides a project everywhere and removes the checkouts of the worktrees dsd created for it.
Their branches stay, so no committed work is lost; uncommitted work blocks the archive unless forced.
Adopted worktrees are never deleted, only unlisted. Docs, plans and runs are kept, and restoring the
project recreates its worktrees from their branches.
"""

from __future__ import annotations

import tomllib
from datetime import datetime

import tomli_w

from . import review, worktrees
from .project import Project


class ArchiveError(Exception):
    pass


def preview(project: Project) -> dict:
    wts = worktrees.list_worktrees(project) if review.is_repo(project.repo) else []
    remove = [w for w in wts if w["origin"] == "dsd" and w["exists"]]
    return {
        "project": project.name,
        "remove": [{"name": w["name"], "branch": w["branch"], "path": w["path"], "dirty": w.get("dirty", 0)} for w in remove],
        "unlist": [{"name": w["name"], "branch": w["branch"], "path": w["path"]} for w in wts if w["origin"] == "adopted"],
        "blockers": [{"name": w["name"], "dirty": w["dirty"]} for w in remove if w.get("dirty")],
    }


def _set_archived(project: Project, archived: bool) -> None:
    data = tomllib.loads(project.project_file.read_text())
    if archived:
        data["archived"] = True
        data["archived_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    else:
        data.pop("archived", None)
        data.pop("archived_at", None)
    project.project_file.write_text(tomli_w.dumps(data))


def archive_project(project: Project, force: bool = False) -> dict:
    p = preview(project)
    if p["blockers"] and not force:
        names = ", ".join(f"{b['name']} ({b['dirty']})" for b in p["blockers"])
        raise ArchiveError(f"Worktrees with uncommitted changes: {names}. Commit them, or archive with force to discard them.")
    for w in p["remove"]:
        worktrees.remove_worktree(project, w["name"], force=force, park=True)
    _set_archived(project, True)
    return {"archived": project.name, "removed": [w["name"] for w in p["remove"]],
            "unlisted": [w["name"] for w in p["unlist"]]}


def restore_project(project: Project) -> dict:
    _set_archived(project, False)
    restored, missing = worktrees.restore_parked(project) if review.is_repo(project.repo) else ([], [])
    return {"restored_project": project.name, "restored": restored, "missing": missing}
