"""`dsd init`: set up (or repair) a project. Idempotent: re-running changes nothing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import tomli_w

from .ids import ulid
from .managed import upsert_block
from .project import DSD_DIR, INDEX_FILE, PROJECT_FILE, Project, ProjectNotFound, load_project

DOC_SUBDIRS = ("plans", "decisions", "notes", "reports", "experiments")

CLAUDE_START = "<!-- dsd:start (managed by dsd; edits inside this block are overwritten) -->"
CLAUDE_END = "<!-- dsd:end -->"
GITIGNORE_START = "# dsd:start"
GITIGNORE_END = "# dsd:end"


@dataclass
class InitReport:
    project: Project
    actions: list[tuple[str, str]] = field(default_factory=list)  # (action, relative path)

    def add(self, action: str, path: Path) -> None:
        self.actions.append((action, str(path.relative_to(self.project.root))))

    @property
    def changed(self) -> bool:
        return any(a != "unchanged" for a, _ in self.actions)


def template(name: str) -> str:
    return files("dsd.templates").joinpath(name).read_text()


def _write(report: InitReport, path: Path, content: str) -> None:
    if path.exists():
        if path.read_text() == content:
            report.add("unchanged", path)
            return
        action = "updated"
    else:
        action = "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    report.add(action, path)


def _ensure_dir(report: InitReport, path: Path, keep: bool) -> None:
    if path.is_dir():
        return
    path.mkdir(parents=True)
    if keep:  # git doesn't track empty dirs
        (path / ".gitkeep").touch()
    report.add("created", path)


def claude_block(project: Project, active: str = "_none_") -> str:
    return template("claude_block.md").format(name=project.name, active=active)


def refresh_claude_md(project: Project, active_tasks: list[tuple[str, str]]) -> bool:
    """Rewrite the managed CLAUDE.md block with current active tasks. Only touches an existing block."""
    path = project.root / "CLAUDE.md"
    if not path.exists():
        return False
    text = path.read_text()
    if CLAUDE_START not in text or CLAUDE_END not in text:
        return False
    active = ", ".join(f"`{tid}` {title}" for tid, title in active_tasks) or "_none_"
    new = upsert_block(text, CLAUDE_START, CLAUDE_END, claude_block(project, active))
    if new != text:
        path.write_text(new)
        return True
    return False


def init_project(root: Path, name: str | None = None) -> InitReport:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    # 1. project.toml: never regenerate the id of an existing project.
    try:
        project = load_project(root)
        created_project = False
    except ProjectNotFound:
        project = Project(root=root, id=ulid(), name=name or root.name)
        created_project = True
    report = InitReport(project)
    project_file = root / PROJECT_FILE
    if created_project:
        project_file.parent.mkdir(parents=True, exist_ok=True)
        project_file.write_text(tomli_w.dumps(project.to_toml_dict()))
        report.add("created", project_file)
    else:
        report.add("unchanged", project_file)

    # 2. Directories.
    _ensure_dir(report, project.runs_path, keep=False)
    for sub in DOC_SUBDIRS:
        _ensure_dir(report, project.docs_path / sub, keep=sub != "plans")

    # 3. Central plan: create only if missing; never overwrite user content.
    if not project.main_plan_path.exists():
        _write(report, project.main_plan_path, template("main_plan.md").replace("{name}", project.name))
    else:
        report.add("unchanged", project.main_plan_path)

    # 4. .gitignore managed block.
    gitignore = root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    body = f"{project.runs_dir.rstrip('/')}/\n{INDEX_FILE}\n{INDEX_FILE}-*\n{DSD_DIR}/review.json"
    _write(report, gitignore, upsert_block(existing, GITIGNORE_START, GITIGNORE_END, body))

    # 5. CLAUDE.md managed block. Keep the current block if present (it holds live state
    #    such as active tasks); only insert it when missing.
    claude_md = root / "CLAUDE.md"
    existing = claude_md.read_text() if claude_md.exists() else ""
    if CLAUDE_START in existing and CLAUDE_END in existing:
        report.add("unchanged", claude_md)
    else:
        _write(report, claude_md, upsert_block(existing, CLAUDE_START, CLAUDE_END, claude_block(project)))

    # 6. .mcp.json: add the dsd server, preserving any other servers.
    mcp_path = root / ".mcp.json"
    try:
        mcp = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    except json.JSONDecodeError:
        mcp = None  # don't clobber a file we can't parse
    if mcp is not None:
        servers = mcp.setdefault("mcpServers", {})
        if "dsd" not in servers:
            servers["dsd"] = {"command": "dsd", "args": ["mcp"]}
            _write(report, mcp_path, json.dumps(mcp, indent=2) + "\n")
        else:
            report.add("unchanged", mcp_path)

    # 7. Claude Code skills: install missing ones; never overwrite user edits.
    skills_src = files("dsd.templates").joinpath("skills")
    for skill in sorted(skills_src.iterdir(), key=lambda s: s.name):
        if not skill.is_dir():
            continue
        dest = root / ".claude" / "skills" / skill.name / "SKILL.md"
        if dest.exists():
            report.add("unchanged", dest)
        else:
            _write(report, dest, skill.joinpath("SKILL.md").read_text())

    return report


__all__ = ["init_project", "InitReport", "claude_block", "CLAUDE_START", "CLAUDE_END", "DSD_DIR"]
