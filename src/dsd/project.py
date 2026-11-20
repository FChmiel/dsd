"""Locating and loading dsd projects.

A project's state (docs, plans, runs, index, review comments) lives outside the code, in
~/.dsd/projects/<id>/ (DSD_HOME overrides ~/.dsd). Its project.toml records the repo the project is
for and an optional scope (a repo-relative subdirectory). dsd never writes into the repo itself.

Several projects can share a repo. Inside a worktree, the project that owns it (worktrees.json) wins;
elsewhere the most specific scope wins, then the repo's default project (`default = true`, else the
oldest).
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_ENV = "DSD_PROJECT_ROOT"
PROJECT_FILE = "project.toml"
INDEX_FILE = "index.db"
DOCS_DIR = "docs"
RUNS_DIR = "runs"
WORKTREES_FILE = "worktrees.json"


class ProjectNotFound(Exception):
    pass


def dsd_home() -> Path:
    return Path(os.environ.get("DSD_HOME", Path.home() / ".dsd"))


def projects_dir() -> Path:
    return dsd_home() / "projects"


@dataclass
class Project:
    id: str
    name: str
    data_dir: Path
    repo: Path
    root: Path
    scope: str | None = None
    default: bool = False
    backup: list[dict] = field(default_factory=list)
    worktree_cfg: dict = field(default_factory=dict)
    docs_dir: str = DOCS_DIR

    @property
    def is_worktree(self) -> bool:
        return self.root != self.repo

    @property
    def work_dir(self) -> Path:
        return self.root / self.scope if self.scope else self.root

    @property
    def project_file(self) -> Path:
        return self.data_dir / PROJECT_FILE

    @property
    def docs_path(self) -> Path:
        return self.data_dir / DOCS_DIR

    @property
    def plans_path(self) -> Path:
        return self.docs_path / "plans"

    @property
    def main_plan_path(self) -> Path:
        return self.plans_path / "main.md"

    @property
    def runs_path(self) -> Path:
        return self.data_dir / RUNS_DIR

    @property
    def index_path(self) -> Path:
        return self.data_dir / INDEX_FILE

    def to_toml_dict(self) -> dict:
        data: dict = {"id": self.id, "name": self.name, "repo": str(self.repo)}
        if self.scope:
            data["scope"] = self.scope
        if self.default:
            data["default"] = True
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
        return None
    return gitdir.parent.parent.parent.resolve()


def checkout_of(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def load_project(data_dir: Path, root: Path | None = None) -> Project:
    path = data_dir / PROJECT_FILE
    if not path.is_file():
        raise ProjectNotFound(f"No {PROJECT_FILE} in {data_dir}")
    data = tomllib.loads(path.read_text())
    repo = Path(data["repo"])
    return Project(
        id=data["id"],
        name=data.get("name", repo.name),
        data_dir=data_dir,
        repo=repo,
        root=root or repo,
        scope=data.get("scope") or None,
        default=bool(data.get("default", False)),
        backup=list(data.get("backup", [])),
        worktree_cfg=dict(data.get("worktree", {})),
    )


def all_projects() -> list[Project]:
    base = projects_dir()
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if not (d / PROJECT_FILE).is_file():
            continue
        try:
            out.append(load_project(d))
        except (KeyError, tomllib.TOMLDecodeError):
            continue
    return out


def _covers(scope: str | None, rel: str) -> bool:
    return not scope or rel == scope or rel.startswith(scope + "/")


def owned_worktrees(project: Project) -> set[str]:
    try:
        meta = json.loads((project.data_dir / WORKTREES_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    return {m["path"] for m in meta.values() if "path" in m}


def pick_default(projects: list[Project]) -> Project:
    return next((p for p in projects if p.default), None) or min(projects, key=lambda p: p.id)


def repo_projects(repo: Path, scope: str | None | bool = False) -> list[Project]:
    """Projects for `repo` (any scope, or exactly `scope` when given)."""
    return [p for p in all_projects() if p.repo.resolve() == repo.resolve() and (scope is False or p.scope == scope)]


def find_project(start: Path | None = None) -> Project:
    """The project for `start` (default: cwd): a path in a repo, a subdirectory, a linked worktree, or a data dir.

    The closest enclosing checkout wins; within it, the project with the most specific scope.
    """
    here = (start or Path.cwd()).resolve()
    projects = all_projects()
    base = projects_dir().resolve()
    if here == base or base in here.parents:
        rel = here.relative_to(base).parts
        for p in projects:
            if rel and p.id == rel[0]:
                return p
    for checkout in (here, *here.parents):
        repo = main_checkout_of(checkout) or checkout
        same = [p for p in projects if p.repo.resolve() == repo]
        if not same:
            continue
        if checkout != repo:
            owner = next((p for p in same if str(checkout) in owned_worktrees(p)), None)
            if owner:
                return replace(owner, root=checkout)
        rel = "" if here == checkout else here.relative_to(checkout).as_posix()
        matches = [p for p in same if _covers(p.scope, rel)]
        if matches:
            depth = max(len(Path(p.scope).parts) if p.scope else 0 for p in matches)
            best = [p for p in matches if (len(Path(p.scope).parts) if p.scope else 0) == depth]
            return replace(pick_default(best), root=checkout)
    raise ProjectNotFound(f"No dsd project for {here}. Run `dsd init` in the repo to start one.")


def current_project() -> Project:
    """The project for $DSD_PROJECT_ROOT if set (any path find_project accepts), else for the cwd."""
    override = os.environ.get(PROJECT_ENV)
    return find_project(Path(override) if override else None)
