"""Git worktrees for parallel agent sessions.

Each Claude session can get its own worktree + branch (dsd/<name>) so agents never trample each
other's working copies. Worktrees live under ~/.dsd/worktrees/<project>/<name>; metadata (base
branch, linked task) is kept in the main checkout's .dsd/worktrees.json.

Shared state stays central: a run started inside a worktree is stored in the main checkout's
.dsd/runs (see Project.state_root), tagged with the worktree and branch.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import registry
from .project import PROJECT_FILE, Project

BRANCH_PREFIX = "dsd/"
DEFAULT_COPY = [".env", ".env.local"]
DSD_FILES = [PROJECT_FILE, ".dsd/benchmarks.toml", ".mcp.json", "CLAUDE.md", ".claude/skills"]

_ADJ = ["amber", "brisk", "calm", "deft", "eager", "fleet", "gentle", "keen", "lucid", "nimble", "quiet", "rapid",
        "sharp", "steady", "swift", "tidy", "vivid", "wise"]
_NOUN = ["otter", "heron", "lynx", "falcon", "badger", "marten", "wren", "ibis", "panda", "orca", "tern", "hare",
         "fox", "koala", "mole", "puffin", "raven", "seal"]


class WorktreeError(Exception):
    pass


@dataclass
class GitResult:
    code: int
    out: str
    err: str


def _git(cwd: Path, *args: str, check: bool = True) -> GitResult:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    res = GitResult(p.returncode, p.stdout, p.stderr)
    if check and p.returncode != 0:
        raise WorktreeError((p.stderr or p.stdout).strip() or f"git {' '.join(args)} failed")
    return res


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "wt"


def random_name() -> str:
    return f"{random.choice(_ADJ)}-{random.choice(_NOUN)}"


def base_dir(project: Project) -> Path:
    return registry.home() / "worktrees" / f"{slugify(project.name, 30)}-{project.id[-6:].lower()}"


def _meta_file(project: Project) -> Path:
    return project.state_root / ".dsd" / "worktrees.json"


def _load_meta(project: Project) -> dict[str, dict]:
    try:
        return json.loads(_meta_file(project).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_meta(project: Project, meta: dict[str, dict]) -> None:
    f = _meta_file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(meta, indent=2) + "\n")


def _main(project: Project) -> Path:
    return project.state_root


def current_branch(root: Path) -> str | None:
    r = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    return r.out.strip() or None


def branches(project: Project) -> list[str]:
    r = _git(_main(project), "for-each-ref", "--format=%(refname:short)", "refs/heads", check=False)
    return [b for b in r.out.splitlines() if b]


def _porcelain(project: Project) -> list[dict]:
    out = _git(_main(project), "worktree", "list", "--porcelain").out
    items, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur["path"] = str(Path(val).resolve())
        elif key == "HEAD":
            cur["head"] = val
        elif key == "branch":
            cur["branch"] = val.removeprefix("refs/heads/")
        elif key in ("detached", "locked", "prunable", "bare"):
            cur[key] = True
    return items


def is_bootstrap(rel: str, copied: list[str]) -> bool:
    """Files dsd copied into the worktree (wiring, .env): not the agent's changes, never committed."""
    rel = rel.strip().strip('"').rstrip("/")
    return any(rel == c or rel.startswith(c.rstrip("/") + "/") for c in copied)


def _status(path: Path, base: str | None, copied: list[str] | None = None) -> dict:
    st = [ln for ln in _git(path, "status", "--porcelain", check=False).out.splitlines()
          if not is_bootstrap(ln[3:].split(" -> ")[-1], copied or [])]
    info: dict = {"dirty": len(st), "ahead": None, "behind": None, "last_commit": None}
    if base:
        r = _git(path, "rev-list", "--left-right", "--count", f"{base}...HEAD", check=False)
        if r.code == 0 and r.out.strip():
            behind, ahead = r.out.split()
            info["ahead"], info["behind"] = int(ahead), int(behind)
    lc = _git(path, "log", "-1", "--format=%h%x1f%s%x1f%ad", "--date=iso-strict", check=False).out.strip()
    if lc:
        h, s, d = (lc.split("\x1f") + ["", ""])[:3]
        info["last_commit"] = {"short": h, "subject": s, "date": d}
    return info


def list_worktrees(project: Project, with_status: bool = True) -> list[dict]:
    """The main checkout first, then linked worktrees (dsd-created ones carry base/task metadata)."""
    main = _main(project).resolve()
    meta = _load_meta(project)
    by_path = {v["path"]: (k, v) for k, v in meta.items()}
    out = []
    for item in _porcelain(project):
        path = Path(item["path"])
        is_main = path == main
        name, m = by_path.get(str(path), (None, {}))
        if is_main:
            name = "main"
        name = name or path.name
        entry = {
            "name": name, "path": str(path), "is_main": is_main, "branch": item.get("branch"),
            "head": item.get("head"), "detached": item.get("detached", False), "managed": bool(m),
            "base": m.get("base"), "task": m.get("task"), "created": m.get("created"), "copied": m.get("copied", []),
            "exists": path.is_dir(), "prunable": item.get("prunable", False),
        }
        if with_status and entry["exists"]:
            entry.update(_status(path, None if is_main else entry["base"], entry["copied"]))
        out.append(entry)
    out.sort(key=lambda e: (not e["is_main"], -(e["created"] or 0)))
    return out


def get_worktree(project: Project, name: str | None) -> dict:
    """Resolve 'main'/None or a worktree name (or branch) to its entry."""
    wts = list_worktrees(project, with_status=False)
    if not name or name == "main":
        return wts[0]
    for w in wts:
        if w["name"] == name or w["branch"] == name or w["branch"] == f"{BRANCH_PREFIX}{name}":
            return w
    raise WorktreeError(f"No worktree '{name}'")


def _bootstrap(project: Project, src: Path, dest: Path) -> list[str]:
    """Copy dsd wiring and configured local files (e.g. .env) that git doesn't carry into the worktree."""
    copied = []
    copy = list(DSD_FILES) + list(project.worktree_cfg.get("copy", DEFAULT_COPY))
    for rel in copy:
        s, d = src / rel, dest / rel
        if not s.exists() or d.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
        copied.append(rel)
    return copied


def create_worktree(project: Project, name: str | None = None, base: str | None = None,
                    task: str | None = None, task_title: str | None = None) -> dict:
    main = _main(project)
    if _git(main, "rev-parse", "--verify", "-q", "HEAD", check=False).code != 0:
        raise WorktreeError("The repo has no commits yet; commit once before creating worktrees.")
    if not name:
        name = slugify(f"{task}-{task_title}" if task and task_title else task or random_name(), 40)
    name = slugify(name, 40)
    base = base or current_branch(main) or _git(main, "rev-parse", "HEAD").out.strip()
    if _git(main, "rev-parse", "--verify", "-q", f"{base}^{{commit}}", check=False).code != 0:
        raise WorktreeError(f"Unknown base '{base}'")

    existing_branches = set(branches(project))
    meta = _load_meta(project)
    root = base_dir(project)
    candidate, n = name, 1
    while (candidate in meta or f"{BRANCH_PREFIX}{candidate}" in existing_branches
           or (root / candidate).exists()):
        n += 1
        candidate = f"{name}-{n}"
    name = candidate
    branch = f"{BRANCH_PREFIX}{name}"
    path = root / name
    root.mkdir(parents=True, exist_ok=True)
    from .init import refresh_gitignore

    refresh_gitignore(project)  # make sure .dsd/worktrees.json is ignored in older projects
    _git(main, "worktree", "add", "-b", branch, str(path), base)
    copied = _bootstrap(project, main, path)
    meta[name] = {"path": str(path.resolve()), "branch": branch, "base": base, "task": task,
                  "created": time.time(), "copied": copied}
    _save_meta(project, meta)
    return get_worktree(project, name) | {"copied": copied}


def remove_worktree(project: Project, name: str, force: bool = False, delete_branch: bool = False) -> dict:
    wt = get_worktree(project, name)
    if wt["is_main"]:
        raise WorktreeError("Can't remove the main checkout")
    path = Path(wt["path"])
    if path.is_dir() and not force:
        n = _status(path, None, wt["copied"])["dirty"]
        if n:
            raise WorktreeError(f"'{wt['name']}' has {n} uncommitted change(s); commit them or remove with force")
    args = ["worktree", "remove"] + (["--force"] if force else []) + [str(path)]
    if path.is_dir():
        _git(_main(project), *args)
    else:
        _git(_main(project), "worktree", "prune")
    branch_deleted = False
    if delete_branch and wt["branch"]:
        # explicit request (UI/CLI warn about unmerged commits), so delete even if unmerged
        r = _git(_main(project), "branch", "-D", wt["branch"], check=False)
        if r.code != 0:
            raise WorktreeError(f"Worktree removed, but branch {wt['branch']} was kept: {r.err.strip()}")
        branch_deleted = True
    meta = _load_meta(project)
    meta.pop(wt["name"], None)
    _save_meta(project, meta)
    return {"removed": wt["name"], "branch_deleted": branch_deleted}


def commit_all(project: Project, name: str, message: str) -> dict:
    wt = get_worktree(project, name)
    path = Path(wt["path"])
    _git(path, "add", "-A")
    if wt["copied"]:  # keep dsd's bootstrap copies out of the branch
        _git(path, "reset", "-q", "--", *wt["copied"], check=False)
    if not _git(path, "diff", "--cached", "--name-only", check=False).out.strip():
        raise WorktreeError("Nothing to commit")
    _git(path, "commit", "-m", message)
    return {"committed": _git(path, "rev-parse", "--short", "HEAD").out.strip()}


def merge_worktree(project: Project, name: str, strategy: str = "merge", message: str | None = None) -> dict:
    """Merge a worktree's branch into its base, in the main checkout. Aborts cleanly on conflict."""
    wt = get_worktree(project, name)
    if wt["is_main"]:
        raise WorktreeError("Pick a worktree to merge")
    main = _main(project)
    base = wt["base"] or current_branch(main)
    path = Path(wt["path"])
    if path.is_dir() and _status(path, None, wt["copied"])["dirty"]:
        raise WorktreeError(f"'{wt['name']}' has uncommitted changes; commit them first")
    if current_branch(main) != base:
        raise WorktreeError(f"The main checkout is on '{current_branch(main)}', not '{base}'; switch it to {base} first")
    if _git(main, "status", "--porcelain", "--untracked-files=no", check=False).out.strip():
        raise WorktreeError("The main checkout has uncommitted changes; commit or stash them first")
    ahead = _git(main, "rev-list", "--count", f"{base}..{wt['branch']}", check=False).out.strip()
    if ahead == "0":
        raise WorktreeError(f"{wt['branch']} has no commits that aren't already on {base}")
    msg = message or f"Merge {wt['branch']}" + (f"\n\nTask: {wt['task']}" if wt.get("task") else "")
    if strategy == "squash":
        r = _git(main, "merge", "--squash", wt["branch"], check=False)
        if r.code != 0:
            _git(main, "reset", "--merge", check=False)
            raise WorktreeError(f"Squash merge failed (conflicts?): {(r.out + r.err).strip()[:400]}")
        _git(main, "commit", "-m", msg)
    else:
        r = _git(main, "merge", "--no-ff", "-m", msg, wt["branch"], check=False)
        if r.code != 0:
            conflicts = _git(main, "diff", "--name-only", "--diff-filter=U", check=False).out.split()
            _git(main, "merge", "--abort", check=False)
            if not conflicts:
                raise WorktreeError(f"Merge failed: {(r.err or r.out).strip()[:400]}")
            raise WorktreeError("Merge conflict in " + ", ".join(conflicts)
                                + "; merge aborted. Rebase the worktree on " + base + " and retry.")
    return {"merged": wt["branch"], "into": base, "commit": _git(main, "rev-parse", "--short", "HEAD").out.strip()}


def setup_command(project: Project) -> str | None:
    cmd = project.worktree_cfg.get("setup")
    return str(cmd) if cmd else None
