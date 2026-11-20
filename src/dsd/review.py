"""Diff review: what changed (working tree or a commit), and line comments to hand back to an agent.

Comments live in the project's data dir (review.json) so both the app and agents (via MCP) see the same list.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from .ids import ulid
from .project import Project

MAX_LINES_PER_FILE = 4000
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _git(root: Path, *args: str, ok_codes=(0,)) -> str:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, errors="replace")
    if out.returncode not in ok_codes:
        return ""
    return out.stdout


def has_head(root: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root, capture_output=True).returncode == 0


def is_repo(root: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=root, capture_output=True).returncode == 0


def parse_diff(text: str) -> list[dict]:
    """Parse a multi-file unified diff into [{path, old_path, status, binary, hunks:[{header, lines}]}]."""
    files: list[dict] = []
    cur: dict | None = None
    hunk: dict | None = None
    old_no = new_no = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = {"path": m.group(2) if m else line[11:], "old_path": m.group(1) if m else None,
                   "status": "modified", "binary": False, "hunks": [], "truncated": False, "additions": 0, "deletions": 0}
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif line.startswith("rename to "):
            cur["status"] = "renamed"
            cur["path"] = line[len("rename to "):]
        elif line.startswith("Binary files"):
            cur["binary"] = True
        elif line.startswith("+++ ") or line.startswith("--- "):
            if line.startswith("+++ b/"):
                cur["path"] = line[6:]
            continue
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            if not m:
                continue
            old_no, new_no = int(m.group(1)), int(m.group(3))
            hunk = {"header": line, "lines": []}
            cur["hunks"].append(hunk)
        elif hunk is not None:
            n = sum(len(h["lines"]) for h in cur["hunks"])
            if n >= MAX_LINES_PER_FILE:
                cur["truncated"] = True
                continue
            tag = line[:1]
            body = line[1:]
            if tag == "+":
                hunk["lines"].append({"t": "add", "old": None, "new": new_no, "text": body})
                new_no += 1
                cur["additions"] += 1
            elif tag == "-":
                hunk["lines"].append({"t": "del", "old": old_no, "new": None, "text": body})
                old_no += 1
                cur["deletions"] += 1
            elif tag == "\\":
                continue
            else:
                hunk["lines"].append({"t": "ctx", "old": old_no, "new": new_no, "text": body})
                old_no += 1
                new_no += 1
    return files


def working_changes(project: Project, root: Path | None = None, base: str | None = None,
                    ignore: list[str] | None = None) -> dict:
    """Uncommitted changes in `root` (default: the project checkout).

    With `base`, diff from merge-base(base, HEAD) instead of HEAD, so a worktree's review shows
    everything its agent did on the branch: commits plus uncommitted edits plus new files.
    """
    root = root or project.root
    if not is_repo(root):
        return {"repo": False, "files": []}
    since = "HEAD"
    if base and has_head(root):
        mb = _git(root, "merge-base", base, "HEAD").strip()
        since = mb or "HEAD"
    if has_head(root):
        tracked = _git(root, "diff", since, "--no-color", "-M", "--no-ext-diff")
    else:
        tracked = _git(root, "diff", "--cached", "--no-color", "--no-ext-diff")
    files = parse_diff(tracked)
    untracked = [u for u in _git(root, "ls-files", "--others", "--exclude-standard").splitlines() if u]
    if not has_head(root):
        staged = {f["path"] for f in files}
        untracked += [u for u in _git(root, "diff", "--name-only").splitlines() if u and u not in staged]
    for path in untracked:
        p = root / path
        if not p.is_file():
            continue
        d = _git(root, "diff", "--no-index", "--no-color", "--", "/dev/null", path, ok_codes=(0, 1))
        parsed = parse_diff(d)
        for f in parsed:
            f["path"] = path
            f["status"] = "added"
        files.extend(parsed)
    if ignore:
        from .worktrees import is_bootstrap

        files = [f for f in files if not is_bootstrap(f["path"], ignore)]
    files.sort(key=lambda f: f["path"])
    return {"repo": True, "ref": None, "base": base, "since": since, "files": files}


def commit_changes(project: Project, ref: str) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}|HEAD(~\d+)?", ref):
        raise ValueError("bad ref")
    text = _git(project.root, "show", ref, "--format=", "--no-color", "-M", "--no-ext-diff")
    subject = _git(project.root, "show", "-s", "--format=%h %s", ref).strip()
    return {"repo": True, "ref": ref, "subject": subject, "files": parse_diff(text)}


def recent_commits(project: Project, n: int = 30) -> list[dict]:
    if not has_head(project.root):
        return []
    out = _git(project.root, "log", f"-{n}", "--format=%H%x1f%h%x1f%ad%x1f%an%x1f%s", "--date=iso-strict")
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            commits.append({"sha": parts[0], "short": parts[1], "date": parts[2], "author": parts[3], "subject": parts[4]})
    return commits


# ---------------------------------------------------------------- comments

def _comments_file(project: Project) -> Path:
    return project.data_dir / "review.json"


def load_comments(project: Project) -> list[dict]:
    try:
        return json.loads(_comments_file(project).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(project: Project, comments: list[dict]) -> None:
    f = _comments_file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(comments, indent=2) + "\n")


def add_comment(project: Project, path: str, line: int | None, text: str, side: str = "new",
                code: str | None = None, ref: str | None = None, worktree: str | None = None) -> dict:
    c = {"id": ulid(), "path": path, "line": line, "side": side, "text": text.strip(), "code": code,
         "ref": ref, "worktree": worktree, "status": "open", "created": time.time()}
    comments = load_comments(project)
    comments.append(c)
    _save(project, comments)
    return c


def update_comment(project: Project, cid: str, **fields) -> dict:
    comments = load_comments(project)
    for c in comments:
        if c["id"] == cid:
            c.update({k: v for k, v in fields.items() if k in ("text", "status")})
            _save(project, comments)
            return c
    raise KeyError(cid)


def delete_comment(project: Project, cid: str) -> None:
    _save(project, [c for c in load_comments(project) if c["id"] != cid])


def format_for_agent(comments: list[dict]) -> str:
    lines = ["Please address these review comments on your changes:", ""]
    for i, c in enumerate(comments, 1):
        loc = f"{c['path']}:{c['line']}" if c.get("line") else c["path"]
        if c.get("ref"):
            loc += f" (commit {c['ref'][:8]})"
        lines.append(f"{i}. {loc} — {c['text']}  [id {c['id']}]")
        if c.get("code"):
            lines.append(f"   > {c['code'].strip()}")
    lines += ["", "When done, mark them resolved with the dsd review_resolve tool (or tell me)."]
    return "\n".join(lines)
