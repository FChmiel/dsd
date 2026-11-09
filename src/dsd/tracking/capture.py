"""Automatic capture of reproducibility context: git state, command, environment, dataset refs."""

from __future__ import annotations

import getpass
import hashlib
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def git_info(root: Path, diff_out: Path | None = None) -> dict | None:
    sha = _git(root, "rev-parse", "HEAD")
    if sha is None:
        # Repo with no commits yet, or not a repo at all.
        if _git(root, "rev-parse", "--git-dir") is None:
            return None
        sha = ""
    branch = (_git(root, "symbolic-ref", "--short", "-q", "HEAD") or "").strip() or None
    status = _git(root, "status", "--porcelain") or ""
    dirty = bool(status.strip())
    info = {"sha": sha.strip() or None, "branch": branch, "dirty": dirty}
    if dirty and diff_out is not None:
        diff = _git(root, "diff", "HEAD") if info["sha"] else _git(root, "diff")
        untracked = [ln[3:] for ln in status.splitlines() if ln.startswith("??")]
        text = diff or ""
        if untracked:
            text += "\n# untracked files:\n" + "\n".join(f"#   {u}" for u in untracked) + "\n"
        diff_out.write_text(text)
    remote = (_git(root, "config", "--get", "remote.origin.url") or "").strip()
    if remote:
        info["remote"] = remote
    return info


def env_info(root: Path) -> dict:
    info = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "host": socket.gethostname(),
    }
    for lock in ("uv.lock", "poetry.lock", "requirements.txt", "pixi.lock"):
        p = root / lock
        if p.is_file():
            info["lockfile"] = lock
            info["lockfile_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            break
    return info


def packages() -> dict[str, str]:
    from importlib.metadata import distributions

    out = {}
    for d in distributions():
        name = d.metadata.get("Name")
        if name:
            out[name] = d.version
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def current_user() -> str:
    try:
        return os.environ.get("DSD_USER") or getpass.getuser()
    except Exception:
        return "unknown"


def dataset(name: str | None = None, id: str | None = None, uri: str | None = None,
            config: str | os.PathLike | None = None, **extra) -> dict:
    """A dataset reference: an id, a link (GitHub, S3, URL) and/or a config file (hashed at run time)."""
    ref: dict = {"name": name, "id": id, "uri": uri}
    if config is not None:
        p = Path(config)
        ref["config"] = str(config)
        if p.is_file():
            ref["config_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    ref.update(extra)
    return {k: v for k, v in ref.items() if v is not None}
