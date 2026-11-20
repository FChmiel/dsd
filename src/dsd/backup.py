"""Backups behind a small interface. Phase 0 ships a local snapshot target.

Local snapshots: <path>/<project-id>/<YYYYmmdd-HHMMSS>/... with unchanged files hard-linked to the
previous snapshot (rsync --link-dest style), so each snapshot is complete but cheap. Point `path`
at an iCloud/Dropbox folder for off-machine copies. Later: git and s3 targets, same interface.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import tomli_w

from .project import PROJECT_FILE, RUNS_DIR, Project

DEFAULT_INCLUDE = ["docs", PROJECT_FILE, "benchmarks.toml"]


@dataclass
class BackupResult:
    snapshot: str
    location: Path
    files: int
    linked: int
    copied: int


@dataclass
class Snapshot:
    name: str
    path: Path
    files: int


class BackupTarget(Protocol):
    name: str

    def push(self, project: Project, paths: list[str]) -> BackupResult: ...
    def list_snapshots(self, project: Project) -> list[Snapshot]: ...
    def restore(self, project: Project, snapshot: str, dest: Path) -> int: ...


class LocalTarget:
    def __init__(self, name: str, path: str):
        self.name = name
        self.base = Path(os.path.expanduser(path))

    def _root(self, project: Project) -> Path:
        return self.base / project.id

    def list_snapshots(self, project: Project) -> list[Snapshot]:
        root = self._root(project)
        if not root.is_dir():
            return []
        snaps = []
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                snaps.append(Snapshot(d.name, d, sum(1 for f in d.rglob("*") if f.is_file())))
        return snaps

    def push(self, project: Project, paths: list[str]) -> BackupResult:
        root = self._root(project)
        root.mkdir(parents=True, exist_ok=True)
        prev = self.list_snapshots(project)
        prev_dir = prev[-1].path if prev else None
        name = datetime.now().strftime("%Y%m%d-%H%M%S")
        n = 0
        while (root / name).exists():
            n += 1
            name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}"
        tmp = root / f".{name}.partial"
        files = linked = copied = 0
        for rel in paths:
            src = project.data_dir / rel
            if not src.exists():
                continue
            sources = [src] if src.is_file() else [f for f in src.rglob("*") if f.is_file()]
            for f in sources:
                r = f.relative_to(project.data_dir)
                dest = tmp / r
                dest.parent.mkdir(parents=True, exist_ok=True)
                old = prev_dir / r if prev_dir else None
                st = f.stat()
                if old is not None and old.is_file():
                    ost = old.stat()
                    if ost.st_size == st.st_size and int(ost.st_mtime) == int(st.st_mtime):
                        os.link(old, dest)
                        linked += 1
                        files += 1
                        continue
                shutil.copy2(f, dest)
                copied += 1
                files += 1
        tmp.rename(root / name)  # atomic: no half-written snapshots
        return BackupResult(name, root / name, files, linked, copied)

    def restore(self, project: Project, snapshot: str, dest: Path) -> int:
        src = self._root(project) / snapshot
        if not src.is_dir():
            raise FileNotFoundError(f"No snapshot '{snapshot}' in {self._root(project)}")
        count = 0
        for f in src.rglob("*"):
            if f.is_file():
                out = dest / f.relative_to(src)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
                count += 1
        return count


def targets(project: Project) -> list[BackupTarget]:
    out: list[BackupTarget] = []
    for i, cfg in enumerate(project.backup):
        kind = cfg.get("kind", "local")
        name = cfg.get("name", f"{kind}{i if i else ''}")
        if kind == "local":
            out.append(LocalTarget(name, cfg["path"]))
        else:
            raise ValueError(f"Backup kind '{kind}' is not supported yet (planned: git, s3)")
    return out


def include_paths(project: Project, cfg: dict | None = None) -> list[str]:
    return list((cfg or {}).get("include", DEFAULT_INCLUDE))


def add_local_target(project: Project, path: str, name: str = "local", include_runs: bool = False) -> dict:
    file = project.project_file
    data = tomllib.loads(file.read_text())
    entries = [b for b in data.get("backup", []) if b.get("name", "local") != name]
    include = DEFAULT_INCLUDE + ([RUNS_DIR] if include_runs else [])
    entry = {"name": name, "kind": "local", "path": path, "include": include}
    entries.append(entry)
    data["backup"] = entries
    file.write_text(tomli_w.dumps(data))
    project.backup = entries
    return entry
