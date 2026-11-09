"""Known projects for the app's project switcher (~/.dsd/projects.json, override with DSD_HOME)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .project import Project, ProjectNotFound, load_project


def home() -> Path:
    return Path(os.environ.get("DSD_HOME", Path.home() / ".dsd"))


def _file() -> Path:
    return home() / "projects.json"


def _read() -> list[str]:
    try:
        return list(json.loads(_file().read_text()).get("projects", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def register(root: Path) -> None:
    root_s = str(Path(root).resolve())
    roots = _read()
    if root_s in roots:
        return
    roots.append(root_s)
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps({"projects": roots}, indent=2) + "\n")


def unregister(root: Path) -> None:
    root_s = str(Path(root).resolve())
    roots = [r for r in _read() if r != root_s]
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps({"projects": roots}, indent=2) + "\n")


def projects() -> list[Project]:
    out, seen = [], set()
    for r in _read():
        try:
            p = load_project(Path(r))
        except ProjectNotFound:
            continue
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out
