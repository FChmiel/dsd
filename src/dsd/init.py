"""`dsd init`: start a project for a repo, under ~/.dsd/projects/<id>/. Writes nothing to the repo; re-running changes nothing."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path, PurePosixPath

import tomli_w

from .ids import ulid
from .project import Project, checkout_of, main_checkout_of, pick_default, projects_dir, repo_projects

DOC_SUBDIRS = ("plans", "decisions", "analytics", "notes", "reports", "experiments")


@dataclass
class InitReport:
    project: Project
    actions: list[tuple[str, str]] = field(default_factory=list)  # (action, path relative to the data dir)

    def add(self, action: str, path: Path) -> None:
        self.actions.append((action, str(path.relative_to(self.project.data_dir))))

    @property
    def changed(self) -> bool:
        return any(a != "unchanged" for a, _ in self.actions)


def template(name: str) -> str:
    return files("dsd.templates").joinpath(name).read_text()


def normalize_scope(repo: Path, scope: str | None) -> str | None:
    if not scope:
        return None
    rel = PurePosixPath(scope.strip().replace("\\", "/").strip("/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Scope must be a subdirectory of the repo, got '{scope}'")
    if str(rel) in ("", "."):
        return None
    if not (repo / rel).is_dir():
        raise ValueError(f"Scope '{rel}' is not a directory in {repo}")
    return str(rel)


def init_project(path: Path, name: str | None = None, scope: str | None = None) -> InitReport:
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"{path} is not a directory")
    checkout = checkout_of(path) or path
    repo = main_checkout_of(checkout) or checkout
    scope = normalize_scope(repo, scope)

    same = repo_projects(repo, scope)
    archived = next((p for p in repo_projects(repo, scope, include_archived=True) if p.archived and p.name == name), None)
    if name and archived:
        raise ValueError(f"The project '{name}' on {repo} is archived. Restore it with `dsd restore {name}`.")
    if name:
        project = next((p for p in same if p.name == name), None)
    else:
        project = pick_default(same) if same else None
    if project is None:
        pid = ulid()
        default_name = PurePosixPath(scope).name if scope else repo.name
        project = Project(id=pid, name=name or default_name, data_dir=projects_dir() / pid,
                          repo=repo, root=repo, scope=scope)
        report = InitReport(project)
        project.data_dir.mkdir(parents=True)
        project.project_file.write_text(tomli_w.dumps(project.to_toml_dict()))
        report.add("created", project.project_file)
    else:
        report = InitReport(project)
        report.add("unchanged", project.project_file)

    for d in (project.runs_path, *(project.docs_path / sub for sub in DOC_SUBDIRS)):
        if not d.is_dir():
            d.mkdir(parents=True)
            report.add("created", d)

    if project.main_plan_path.exists():
        report.add("unchanged", project.main_plan_path)
    else:
        project.main_plan_path.write_text(template("main_plan.md").replace("{name}", project.name))
        report.add("created", project.main_plan_path)
    return report


def set_default(project: Project) -> None:
    """Make `project` the one the repo's main checkout resolves to (among projects with the same scope)."""
    for p in repo_projects(project.repo, project.scope):
        data = tomllib.loads(p.project_file.read_text())
        if p.id == project.id:
            data["default"] = True
        else:
            data.pop("default", None)
        p.project_file.write_text(tomli_w.dumps(data))


__all__ = ["init_project", "InitReport", "normalize_scope", "set_default"]
