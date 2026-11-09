"""Run bundles: the source of truth for experiment runs.

A bundle is a self-contained directory that can be written locally, inside a remote job, or to
object storage, and ingested anywhere:

    <run-id>/
      run.json        identity, status, params, info, refs
      metrics.jsonl   append-only metric points
      artifacts/      files (mainly .html reports, plots)
      artifacts.json  manifest: path, mime, size, sha256, description
      capture/        git.diff, env.json, stdout.log
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
STATUSES = ("queued", "running", "finished", "failed", "killed")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def flatten(d: dict, prefix: str = "") -> dict:
    """{"model": {"eta": 0.1}} -> {"model.eta": 0.1}"""
    out: dict = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.update(flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def to_jsonable(v):
    """Coerce numpy/pandas scalars, paths, sets etc. into JSON-friendly values."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [to_jsonable(x) for x in v]
    if hasattr(v, "item"):  # numpy scalar
        try:
            return v.item()
        except Exception:
            pass
    if hasattr(v, "tolist"):
        try:
            return v.tolist()
        except Exception:
            pass
    return str(v)


class Bundle:
    def __init__(self, path: Path):
        self.path = Path(path)

    # ---- files
    @property
    def run_json(self) -> Path:
        return self.path / "run.json"

    @property
    def metrics_path(self) -> Path:
        return self.path / "metrics.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.path / "artifacts"

    @property
    def manifest_path(self) -> Path:
        return self.path / "artifacts.json"

    @property
    def capture_dir(self) -> Path:
        return self.path / "capture"

    @property
    def id(self) -> str:
        return self.path.name

    def exists(self) -> bool:
        return self.run_json.is_file()

    # ---- create / read / write
    @classmethod
    def create(cls, runs_dir: Path, run_id: str, meta: dict) -> "Bundle":
        b = cls(Path(runs_dir) / run_id)
        b.artifacts_dir.mkdir(parents=True, exist_ok=True)
        b.capture_dir.mkdir(exist_ok=True)
        b.metrics_path.touch()
        data = {"schema": SCHEMA, "id": run_id, **meta}
        b.write_meta(data)
        return b

    def read_meta(self) -> dict:
        return json.loads(self.run_json.read_text())

    def write_meta(self, data: dict) -> None:
        _atomic_write(self.run_json, json.dumps(to_jsonable(data), indent=2) + "\n")

    def update_meta(self, **fields) -> dict:
        data = self.read_meta()
        data.update(fields)
        self.write_meta(data)
        return data

    # ---- metrics
    def append_metrics(self, values: dict, step: int | None = None, t: float | None = None) -> None:
        t = time.time() if t is None else t
        lines = []
        for k, v in values.items():
            row = {"k": str(k), "v": float(v), "t": round(t, 3)}
            if step is not None:
                row["step"] = int(step)
            lines.append(json.dumps(row))
        if lines:
            with open(self.metrics_path, "a") as f:
                f.write("\n".join(lines) + "\n")

    def read_metrics(self) -> list[dict]:
        if not self.metrics_path.exists():
            return []
        out = []
        for line in self.metrics_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerate a torn final line from a killed process
        return out

    # ---- artifacts
    def read_manifest(self) -> list[dict]:
        if not self.manifest_path.exists():
            return []
        try:
            return json.loads(self.manifest_path.read_text())
        except json.JSONDecodeError:
            return []

    def add_artifact(self, src: Path, name: str | None = None, description: str | None = None) -> dict | None:
        src = Path(src)
        dest = self.artifacts_dir / (name or src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        return self.rescan_artifacts({dest.relative_to(self.artifacts_dir).as_posix(): description})

    def write_artifact_text(self, name: str, content: str, description: str | None = None) -> None:
        dest = self.artifacts_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        self.rescan_artifacts({name: description})

    def rescan_artifacts(self, descriptions: dict[str, str | None] | None = None) -> None:
        """Rebuild the manifest from what's on disk, keeping existing descriptions."""
        old = {a["path"]: a for a in self.read_manifest()}
        descriptions = descriptions or {}
        entries = []
        if self.artifacts_dir.is_dir():
            for f in sorted(self.artifacts_dir.rglob("*")):
                if not f.is_file() or f.name.startswith("."):
                    continue
                rel = f.relative_to(self.artifacts_dir).as_posix()
                prev = old.get(rel, {})
                st = f.stat()
                if prev.get("size") == st.st_size and prev.get("mtime") == int(st.st_mtime) and prev.get("sha256"):
                    digest = prev["sha256"]
                else:
                    digest = sha256_file(f)
                desc = descriptions.get(rel) or prev.get("description")
                entries.append({
                    "path": rel,
                    "mime": mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "sha256": digest,
                    "description": desc,
                })
        _atomic_write(self.manifest_path, json.dumps(entries, indent=2) + "\n")

    def signature(self) -> float:
        """Change signature for incremental indexing: newest mtime of the tracked files."""
        mt = 0.0
        for p in (self.run_json, self.metrics_path, self.manifest_path):
            try:
                mt = max(mt, p.stat().st_mtime)
            except FileNotFoundError:
                pass
        return mt


def iter_bundles(runs_dir: Path):
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return
    for d in sorted(runs_dir.iterdir()):
        b = Bundle(d)
        if d.is_dir() and b.exists():
            yield b
