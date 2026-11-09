"""Locating and loading a dsd project (a directory containing .dsd/project.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DSD_DIR = ".dsd"
PROJECT_FILE = f"{DSD_DIR}/project.toml"
INDEX_FILE = f"{DSD_DIR}/index.db"


class ProjectNotFound(Exception):
    pass


@dataclass
class Project:
    root: Path
    id: str
    name: str
    docs_dir: str = "docs"
    runs_dir: str = f"{DSD_DIR}/runs"
    backup: list[dict] = field(default_factory=list)

    @property
    def docs_path(self) -> Path:
        return self.root / self.docs_dir

    @property
    def plans_path(self) -> Path:
        return self.docs_path / "plans"

    @property
    def main_plan_path(self) -> Path:
        return self.plans_path / "main.md"

    @property
    def runs_path(self) -> Path:
        return self.root / self.runs_dir

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_FILE

    def to_toml_dict(self) -> dict:
        data: dict = {
            "id": self.id,
            "name": self.name,
            "docs_dir": self.docs_dir,
            "runs_dir": self.runs_dir,
        }
        if self.backup:
            data["backup"] = self.backup
        return data


def load_project(root: Path) -> Project:
    path = root / PROJECT_FILE
    if not path.is_file():
        raise ProjectNotFound(f"No {PROJECT_FILE} in {root}")
    data = tomllib.loads(path.read_text())
    return Project(
        root=root.resolve(),
        id=data["id"],
        name=data.get("name", root.name),
        docs_dir=data.get("docs_dir", "docs"),
        runs_dir=data.get("runs_dir", f"{DSD_DIR}/runs"),
        backup=list(data.get("backup", [])),
    )


def find_project(start: Path | None = None) -> Project:
    """Walk up from `start` (default: cwd) to the nearest directory with .dsd/project.toml."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / PROJECT_FILE).is_file():
            return load_project(candidate)
    raise ProjectNotFound(f"Not inside a dsd project (no {PROJECT_FILE} found above {here}). Run `dsd init`.")
