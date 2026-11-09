"""SQLite index over run bundles. Pure cache: `rebuild()` recreates it from bundles alone.

Sync is lazy and incremental (by bundle mtime signature), so training jobs never touch the DB.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from pathlib import Path

from ..project import Project
from .bundle import Bundle, flatten, iter_bundles

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, project_id TEXT, name TEXT, benchmark TEXT, task TEXT, status TEXT,
  backend TEXT, external_id TEXT, git_sha TEXT, git_dirty INTEGER, created_at TEXT, ended_at TEXT,
  user TEXT, host TEXT, pid INTEGER, error TEXT, bundle_path TEXT, signature REAL, meta_json TEXT
);
CREATE TABLE IF NOT EXISTS params(run_id TEXT, key TEXT, value_json TEXT, value_num REAL, PRIMARY KEY(run_id, key));
CREATE TABLE IF NOT EXISTS info(run_id TEXT, key TEXT, value_json TEXT, PRIMARY KEY(run_id, key));
CREATE TABLE IF NOT EXISTS metrics(run_id TEXT, key TEXT, step INTEGER, value REAL, t REAL);
CREATE TABLE IF NOT EXISTS metric_summary(
  run_id TEXT, key TEXT, last REAL, min REAL, max REAL, n INTEGER, last_step INTEGER, PRIMARY KEY(run_id, key)
);
CREATE TABLE IF NOT EXISTS artifacts(run_id TEXT, path TEXT, mime TEXT, size INTEGER, sha256 TEXT, description TEXT);
CREATE TABLE IF NOT EXISTS tags(run_id TEXT, tag TEXT);
CREATE TABLE IF NOT EXISTS datasets(run_id TEXT, name TEXT, id TEXT, uri TEXT, config TEXT, config_sha256 TEXT);
CREATE INDEX IF NOT EXISTS ix_runs_bench ON runs(benchmark);
CREATE INDEX IF NOT EXISTS ix_runs_task ON runs(task);
CREATE INDEX IF NOT EXISTS ix_metrics_run ON metrics(run_id, key);
"""

CHILD_TABLES = ("params", "info", "metrics", "metric_summary", "artifacts", "tags", "datasets")


def _num(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class Index:
    def __init__(self, project: Project):
        self.project = project
        project.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(project.index_path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _ensure_schema(self) -> None:
        self.db.executescript(SCHEMA)
        row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if row is None or int(row["value"]) != SCHEMA_VERSION:
            for t in ("runs", *CHILD_TABLES):
                self.db.execute(f"DELETE FROM {t}")
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (str(SCHEMA_VERSION),))
            self.db.commit()

    # ---------------------------------------------------------------- sync
    def sync(self) -> dict:
        known = {r["id"]: r["signature"] for r in self.db.execute("SELECT id, signature FROM runs")}
        seen = set()
        added = updated = 0
        for b in iter_bundles(self.project.runs_path):
            seen.add(b.id)
            sig = b.signature()
            if b.id not in known:
                self._ingest(b, sig)
                added += 1
            elif known[b.id] != sig:
                self._ingest(b, sig)
                updated += 1
        removed = [rid for rid in known if rid not in seen]
        for rid in removed:
            self._delete(rid)
        self.db.commit()
        return {"added": added, "updated": updated, "removed": len(removed)}

    def rebuild(self) -> dict:
        for t in ("runs", *CHILD_TABLES):
            self.db.execute(f"DELETE FROM {t}")
        self.db.commit()
        return self.sync()

    def _delete(self, rid: str) -> None:
        self.db.execute("DELETE FROM runs WHERE id=?", (rid,))
        for t in CHILD_TABLES:
            self.db.execute(f"DELETE FROM {t} WHERE run_id=?", (rid,))

    def _ingest(self, b: Bundle, sig: float) -> None:
        try:
            m = b.read_meta()
        except (json.JSONDecodeError, OSError):
            return  # mid-write; next sync picks it up
        rid = b.id
        self._delete(rid)
        git = m.get("git") or {}
        env = m.get("env") or {}
        self.db.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, m.get("project_id"), m.get("name"), m.get("benchmark"), m.get("task"), m.get("status"),
             m.get("backend"), m.get("external_id"), git.get("sha"), int(bool(git.get("dirty"))),
             m.get("created_at"), m.get("ended_at"), m.get("user"), env.get("host"), m.get("pid"),
             m.get("error"), str(b.path), sig, json.dumps(m)),
        )
        for k, v in flatten(m.get("params") or {}).items():
            self.db.execute("INSERT OR REPLACE INTO params VALUES(?,?,?,?)", (rid, k, json.dumps(v), _num(v)))
        for k, v in (m.get("info") or {}).items():
            self.db.execute("INSERT OR REPLACE INTO info VALUES(?,?,?)", (rid, k, json.dumps(v)))
        for tag in m.get("tags") or []:
            self.db.execute("INSERT INTO tags VALUES(?,?)", (rid, tag))
        for d in m.get("datasets") or []:
            self.db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?)",
                            (rid, d.get("name"), d.get("id"), d.get("uri"), d.get("config"), d.get("config_sha256")))
        summary: dict[str, dict] = {}
        rows = []
        for pt in b.read_metrics():
            k, v, step, t = pt.get("k"), pt.get("v"), pt.get("step"), pt.get("t")
            if k is None or v is None:
                continue
            rows.append((rid, k, step, v, t))
            s = summary.setdefault(k, {"last": v, "min": v, "max": v, "n": 0, "last_step": step})
            s["last"], s["n"] = v, s["n"] + 1
            s["min"], s["max"] = min(s["min"], v), max(s["max"], v)
            if step is not None:
                s["last_step"] = step
        self.db.executemany("INSERT INTO metrics VALUES(?,?,?,?,?)", rows)
        for k, s in summary.items():
            self.db.execute("INSERT INTO metric_summary VALUES(?,?,?,?,?,?,?)",
                            (rid, k, s["last"], s["min"], s["max"], s["n"], s["last_step"]))
        for a in b.read_manifest():
            self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?)",
                            (rid, a["path"], a.get("mime"), a.get("size"), a.get("sha256"), a.get("description")))

    # ---------------------------------------------------------------- reads
    def effective_status(self, row) -> str:
        status = row["status"]
        if status == "running" and row["host"] == socket.gethostname() and row["pid"]:
            if not _pid_alive(int(row["pid"])):
                return "crashed"
        return status

    def resolve_id(self, ref: str) -> str:
        ref = ref.strip()
        ids = [r["id"] for r in self.db.execute("SELECT id FROM runs")]
        exact = [i for i in ids if i == ref.upper()]
        if exact:
            return exact[0]
        up = ref.upper()
        matches = [i for i in ids if i.startswith(up) or i.endswith(up)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError(f"No run matching '{ref}'")
        raise KeyError(f"'{ref}' is ambiguous ({len(matches)} runs); use more characters")

    def runs_basic(self, where_sql: str = "", args: tuple = ()) -> list[dict]:
        rows = self.db.execute(f"SELECT * FROM runs {where_sql} ORDER BY created_at DESC, id DESC", args).fetchall()
        return [self._row_dict(r) for r in rows]

    def _row_dict(self, r) -> dict:
        return {
            "id": r["id"], "name": r["name"], "benchmark": r["benchmark"], "task": r["task"],
            "status": self.effective_status(r), "backend": r["backend"], "external_id": r["external_id"],
            "git_sha": r["git_sha"], "git_dirty": bool(r["git_dirty"]), "created_at": r["created_at"],
            "ended_at": r["ended_at"], "user": r["user"], "error": r["error"], "bundle_path": r["bundle_path"],
        }

    def attach_details(self, runs: list[dict]) -> list[dict]:
        """Add params (flattened), metric summaries (last/min/max), info, tags, artifact count."""
        if not runs:
            return runs
        by_id = {r["id"]: r for r in runs}
        for r in runs:
            r.update(params={}, metrics={}, metric_stats={}, info={}, tags=[], artifacts=0)
        ids = list(by_id)
        chunks = [ids[i:i + 500] for i in range(0, len(ids), 500)]
        for chunk in chunks:
            q = ",".join("?" * len(chunk))
            for row in self.db.execute(f"SELECT run_id,key,value_json FROM params WHERE run_id IN ({q})", chunk):
                by_id[row[0]]["params"][row[1]] = json.loads(row[2])
            for row in self.db.execute(f"SELECT * FROM metric_summary WHERE run_id IN ({q})", chunk):
                by_id[row["run_id"]]["metrics"][row["key"]] = row["last"]
                by_id[row["run_id"]]["metric_stats"][row["key"]] = {
                    "last": row["last"], "min": row["min"], "max": row["max"], "n": row["n"], "last_step": row["last_step"]
                }
            for row in self.db.execute(f"SELECT run_id,key,value_json FROM info WHERE run_id IN ({q})", chunk):
                by_id[row[0]]["info"][row[1]] = json.loads(row[2])
            for row in self.db.execute(f"SELECT run_id,tag FROM tags WHERE run_id IN ({q})", chunk):
                by_id[row[0]]["tags"].append(row[1])
            for row in self.db.execute(f"SELECT run_id,count(*) FROM artifacts WHERE run_id IN ({q}) GROUP BY run_id", chunk):
                by_id[row[0]]["artifacts"] = row[1]
        return runs

    def run_detail(self, rid: str) -> dict:
        r = self.db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if r is None:
            raise KeyError(rid)
        d = self.attach_details([self._row_dict(r)])[0]
        meta = json.loads(r["meta_json"])
        d["meta"] = meta
        d["params_nested"] = meta.get("params", {})
        d["datasets"] = meta.get("datasets", [])
        d["git"] = meta.get("git")
        d["env"] = meta.get("env")
        d["command"] = meta.get("command")
        d["worktree"] = meta.get("worktree")
        d["artifact_list"] = [dict(a) for a in self.db.execute(
            "SELECT path,mime,size,sha256,description FROM artifacts WHERE run_id=? ORDER BY path", (rid,))]
        diff = Path(r["bundle_path"]) / "capture" / "git.diff"
        d["has_diff"] = diff.is_file()
        return d

    def series(self, rids: list[str], keys: list[str] | None = None) -> dict[str, dict[str, list]]:
        """{run_id: {metric: [[step_or_index, value], ...]}} for stepped metrics."""
        out: dict[str, dict[str, list]] = {rid: {} for rid in rids}
        if not rids:
            return out
        q = ",".join("?" * len(rids))
        sql = f"SELECT run_id,key,step,value FROM metrics WHERE run_id IN ({q})"
        args: list = list(rids)
        if keys:
            sql += f" AND key IN ({','.join('?' * len(keys))})"
            args += keys
        sql += " ORDER BY rowid"
        counters: dict[tuple, int] = {}
        for row in self.db.execute(sql, args):
            k = (row[0], row[1])
            i = counters.get(k, 0)
            counters[k] = i + 1
            x = row[2] if row[2] is not None else i
            out[row[0]].setdefault(row[1], []).append([x, row[3]])
        return out

    def benchmarks(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT benchmark, count(*) n, max(created_at) last FROM runs WHERE benchmark IS NOT NULL "
            "GROUP BY benchmark ORDER BY last DESC").fetchall()
        return [{"name": r[0], "runs": r[1], "last_run": r[2]} for r in rows]
