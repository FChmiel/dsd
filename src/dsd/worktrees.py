"""Git worktrees for parallel agent sessions.

Each Claude session can get its own worktree + branch (dsd/<name>) so agents never trample each
other's working copies. Worktrees live under ~/.dsd/worktrees/<project>/<name>; metadata (base
branch, linked task) is kept in the project's data dir (worktrees.json).

Like Pane, dsd only lists the worktrees it owns: ones it created and ones you adopted, plus the
worktree you are working in. Other worktrees of the repo are offered as adoption candidates.

Shared state stays central: a run started inside a worktree is stored in the project's data dir,
tagged with the worktree and branch.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .project import WORKTREES_FILE, Project, checkout_of, dsd_home, owned_worktrees, repo_projects

BRANCH_PREFIX = "dsd/"
DEFAULT_COPY = [".env", ".env.local"]

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
    return dsd_home() / "worktrees" / f"{slugify(project.name, 30)}-{project.id[-6:].lower()}"


def _meta_file(project: Project) -> Path:
    return project.data_dir / WORKTREES_FILE


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
    return project.repo


def current_branch(root: Path) -> str | None:
    r = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    return r.out.strip() or None


def branches(project: Project) -> list[str]:
    r = _git(_main(project), "for-each-ref", "--format=%(refname:short)", "refs/heads", check=False)
    return [b for b in r.out.splitlines() if b]


def default_branch(project: Project) -> str | None:
    """The repo's default branch: origin's HEAD if it exists locally, else main or master."""
    main = _main(project)
    remote = _git(main, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD", check=False).out.strip()
    for name in ([remote.split("/", 1)[1]] if "/" in remote else []) + ["main", "master"]:
        if _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).code == 0:
            return name
    return None


def relevant_branches(project: Project, include: list[Path] | None = None) -> list[str]:
    """Branches worth offering as a base: the default, the main checkout's, and this project's worktrees'."""
    names = [default_branch(project), current_branch(_main(project))]
    names += [w["branch"] for w in list_worktrees(project, with_status=False, include=include)]
    return list(dict.fromkeys(n for n in names if n))


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
    """Files dsd copied into the worktree (e.g. .env): not the agent's changes, never committed."""
    rel = rel.strip().strip('"').rstrip("/")
    return any(rel == c or rel.startswith(c.rstrip("/") + "/") for c in copied)


def _status(path: Path, base: str | None, copied: list[str] | None = None, scope: str | None = None) -> dict:
    spec = ["--", scope] if scope else []
    st = [ln for ln in _git(path, "status", "--porcelain", *spec, check=False).out.splitlines()
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


def _entries(project: Project, include: list[Path] | None = None, everything: bool = False) -> list[dict]:
    main = _main(project).resolve()
    meta = _load_meta(project)
    by_path = {v["path"]: (k, v) for k, v in meta.items()}
    current = {str(c) for c in (checkout_of(Path(p).resolve()) for p in include or []) if c}
    others = set().union(*(owned_worktrees(p) for p in repo_projects(project.repo) if p.id != project.id))
    out = []
    for item in _porcelain(project):
        path = Path(item["path"])
        name, m = by_path.get(str(path), (None, {}))
        if str(path) in others and not m:
            continue
        if path == main:
            name, origin = "main", "main"
        elif m:
            origin = m.get("origin", "dsd")
        elif str(path) in current:
            origin = "current"
        elif everything:
            origin = None
        else:
            continue
        out.append({
            "name": name or path.name, "path": str(path), "is_main": path == main, "origin": origin,
            "branch": item.get("branch"), "head": item.get("head"), "detached": item.get("detached", False),
            "managed": bool(m), "base": m.get("base"), "task": m.get("task"), "created": m.get("created"),
            "copied": m.get("copied", []), "exists": path.is_dir(), "prunable": item.get("prunable", False),
        })
    out.sort(key=lambda e: (not e["is_main"], -(e["created"] or 0)))
    return out


def list_worktrees(project: Project, with_status: bool = True, include: list[Path] | None = None) -> list[dict]:
    """The main checkout first, then the worktrees dsd owns (created or adopted) and any in `include`."""
    out = _entries(project, include)
    if with_status:
        live = [e for e in out if e["exists"]]

        def status(e: dict) -> dict:
            return _status(Path(e["path"]), None if e["is_main"] else e["base"], e["copied"], project.scope)

        with ThreadPoolExecutor(max_workers=8) as pool:
            for e, st in zip(live, pool.map(status, live)):
                e.update(st)
    return out


def candidates(project: Project) -> list[dict]:
    """Worktrees of the repo that dsd doesn't list yet (no status: cheap even with many worktrees)."""
    keep = ("name", "path", "branch", "head", "detached", "exists")
    return [{k: e[k] for k in keep} for e in _entries(project, everything=True) if e["origin"] is None]


def adopt_worktree(project: Project, path: str, task: str | None = None) -> dict:
    target = Path(path).expanduser().resolve()
    cand = next((c for c in candidates(project) if Path(c["path"]) == target), None)
    if cand is None:
        raise WorktreeError(f"{target} is not a worktree of {project.repo} that dsd can adopt")
    meta = _load_meta(project)
    base_name = slugify(target.name, 40)
    name, n = base_name, 1
    while name in meta or name == "main":
        n += 1
        name = f"{base_name}-{n}"
    meta[name] = {"path": str(target), "branch": cand["branch"], "base": current_branch(_main(project)),
                  "task": task, "created": time.time(), "copied": [], "origin": "adopted"}
    _save_meta(project, meta)
    return get_worktree(project, name)


def hide_worktree(project: Project, name: str) -> dict:
    """Stop listing a worktree. Its directory and branch are left alone."""
    wt = get_worktree(project, name)
    meta = _load_meta(project)
    if wt["is_main"] or wt["name"] not in meta:
        raise WorktreeError(f"'{wt['name']}' isn't in dsd's worktree list")
    meta.pop(wt["name"])
    _save_meta(project, meta)
    return {"hidden": wt["name"]}


def move_worktree(project: Project, name: str, dest: Project) -> dict:
    """Hand a worktree (and its metadata) to another project on the same repo."""
    if dest.repo.resolve() != project.repo.resolve() or dest.id == project.id:
        raise WorktreeError(f"'{dest.name}' isn't another project on {project.repo}")
    wt = get_worktree(project, name)
    meta = _load_meta(project)
    if wt["name"] not in meta:
        raise WorktreeError(f"'{wt['name']}' isn't in {project.name}'s worktree list")
    entry = meta.pop(wt["name"])
    dest_meta = _load_meta(dest)
    new, n = wt["name"], 1
    while new in dest_meta:
        n += 1
        new = f"{wt['name']}-{n}"
    dest_meta[new] = entry
    _save_meta(dest, dest_meta)
    _save_meta(project, meta)
    return get_worktree(dest, new)


def get_worktree(project: Project, name: str | None) -> dict:
    """Resolve 'main'/None or a worktree name (or branch) to its entry; any worktree of the repo resolves."""
    wts = _entries(project, everything=True)
    if not name or name == "main":
        return wts[0]
    for w in wts:
        if w["name"] == name or w["branch"] == name or w["branch"] == f"{BRANCH_PREFIX}{name}":
            return w
    raise WorktreeError(f"No worktree '{name}'")


def _bootstrap(project: Project, src: Path, dest: Path) -> list[str]:
    """Copy configured local files (e.g. .env) that git doesn't carry into the worktree."""
    copied = []
    copy = list(project.worktree_cfg.get("copy", DEFAULT_COPY))
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
    _git(main, "worktree", "add", "-b", branch, str(path), base)
    copied = _bootstrap(project, main, path)
    meta[name] = {"path": str(path.resolve()), "branch": branch, "base": base, "task": task,
                  "created": time.time(), "copied": copied, "origin": "dsd"}
    _save_meta(project, meta)
    return get_worktree(project, name) | {"copied": copied}


def remove_worktree(project: Project, name: str, force: bool = False, delete_branch: bool = False,
                    park: bool = False) -> dict:
    """Remove a worktree's checkout. With `park`, keep its metadata so restore_parked can recreate it."""
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
    if park and wt["name"] in meta:
        meta[wt["name"]]["parked"] = True
    else:
        meta.pop(wt["name"], None)
    _save_meta(project, meta)
    return {"removed": wt["name"], "branch_deleted": branch_deleted}


def restore_parked(project: Project) -> tuple[list[str], list[str]]:
    """Recreate parked worktrees from their branches: (restored, missing because the branch is gone)."""
    main = _main(project)
    meta = _load_meta(project)
    have = set(branches(project))
    restored, missing = [], []
    for name, m in list(meta.items()):
        if not m.get("parked"):
            continue
        if m.get("branch") not in have:
            meta.pop(name)
            missing.append(name)
            continue
        path = Path(m["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(main, "worktree", "add", str(path), m["branch"])
        m["copied"] = _bootstrap(project, main, path)
        m.pop("parked")
        restored.append(name)
    _save_meta(project, meta)
    return restored, missing


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
