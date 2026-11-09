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
    worktree_cfg: dict = field(default_factory=dict)  # [worktree] setup = "...", copy = [...]
    main_root: Path | None = None  # set when `root` is a linked git worktree of the main checkout

    @property
    def state_root(self) -> Path:
        """Where shared state (runs, index, review comments) lives: the main checkout, even from a worktree."""
        return self.main_root or self.root

    @property
    def is_worktree(self) -> bool:
        return self.main_root is not None

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
        return self.state_root / self.runs_dir

    @property
    def index_path(self) -> Path:
        return self.state_root / INDEX_FILE

    def to_toml_dict(self) -> dict:
        data: dict = {
            "id": self.id,
            "name": self.name,
            "docs_dir": self.docs_dir,
            "runs_dir": self.runs_dir,
        }
        if self.backup:
            data["backup"] = self.backup
        if self.worktree_cfg:
            data["worktree"] = self.worktree_cfg
        return data


def main_checkout_of(root: Path) -> Path | None:
    """If `root` is a linked git worktree, return the main checkout's root (no subprocess: reads .git file)."""
    git = root / ".git"
    if not git.is_file():
        return None
    text = git.read_text().strip()
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    if gitdir.parent.name != "worktrees":
        return None  # submodule or something else
    return gitdir.parent.parent.parent.resolve()


def load_project(root: Path) -> Project:
    path = root / PROJECT_FILE
    if not path.is_file():
        raise ProjectNotFound(f"No {PROJECT_FILE} in {root}")
    data = tomllib.loads(path.read_text())
    main_root = main_checkout_of(root)
    if main_root is not None:
        try:
            main_id = tomllib.loads((main_root / PROJECT_FILE).read_text()).get("id")
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            main_id = None
        if main_id != data["id"]:
            main_root = None  # different project: keep state local
    return Project(
        root=root.resolve(),
        main_root=main_root,
        worktree_cfg=dict(data.get("worktree", {})),
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
