"""Querying runs: filters, sorting, comparison and benchmark leaderboards.

Field paths: name, status, benchmark, task, tag, params.<key>, metrics.<key>, info.<key>.
Where clauses: "metrics.auc>=0.8", "params.model.eta<0.2", "status=finished", "name~xgb".
"""

from __future__ import annotations

import math
import re
import statistics
import tomllib
from dataclasses import dataclass

import tomli_w

from ..project import Project
from .index import Index

BENCH_FILE = ".dsd/benchmarks.toml"
WHERE_RE = re.compile(r"^\s*([\w.\-/]+)\s*(>=|<=|!=|==|=|>|<|~)\s*(.*?)\s*$")


class QueryError(Exception):
    pass


def _coerce(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.lower() in ("none", "null"):
        return None
    try:
        return float(v)
    except ValueError:
        return v.strip("'\"")


def get_field(run: dict, path: str):
    if path == "tag":
        return run.get("tags", [])
    head, _, rest = path.partition(".")
    if head in ("params", "metrics", "info") and rest:
        return run.get(head, {}).get(rest)
    return run.get(path)


@dataclass
class Where:
    field: str
    op: str
    value: object

    @classmethod
    def parse(cls, s: str) -> "Where":
        m = WHERE_RE.match(s)
        if not m:
            raise QueryError(f"Bad filter '{s}' (expected e.g. metrics.auc>=0.8)")
        return cls(m.group(1), m.group(2), _coerce(m.group(3)))

    def matches(self, run: dict) -> bool:
        actual = get_field(run, self.field)
        v = self.value
        if isinstance(actual, list):  # tags
            if self.op in ("=", "=="):
                return v in actual
            if self.op == "!=":
                return v not in actual
            if self.op == "~":
                return any(str(v).lower() in str(a).lower() for a in actual)
            return False
        if self.op == "~":
            return actual is not None and str(v).lower() in str(actual).lower()
        if self.op in ("=", "=="):
            return actual == v or (actual is not None and str(actual) == str(v))
        if self.op == "!=":
            return not (actual == v or (actual is not None and str(actual) == str(v)))
        if actual is None or v is None:
            return False
        try:
            a, b = float(actual), float(v)
        except (TypeError, ValueError):
            a, b = str(actual), str(v)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[self.op]


def _sort_key(field: str):
    def key(run):
        v = get_field(run, field)
        if v is None:
            return (1, 0, "")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return (0, v, "")
        return (0, 0, str(v))
    return key


def sort_runs(runs: list[dict], sort: str | None) -> list[dict]:
    if not sort:
        return runs
    desc = sort.startswith("-")
    field = sort.lstrip("-+")
    present = [r for r in runs if get_field(r, field) is not None]
    missing = [r for r in runs if get_field(r, field) is None]
    present.sort(key=_sort_key(field), reverse=desc)
    return present + missing


def list_runs(
    idx: Index, *, benchmark: str | None = None, task: str | None = None, status: str | None = None,
    tag: str | None = None, where: list[str] | None = None, sort: str | None = None, limit: int | None = None,
) -> list[dict]:
    clauses, args = [], []
    for col, val in (("benchmark", benchmark), ("task", task)):
        if val:
            clauses.append(f"{col}=?")
            args.append(val)
    sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    runs = idx.attach_details(idx.runs_basic(sql, tuple(args)))
    filters = [Where.parse(w) for w in where or []]
    if status:
        filters.append(Where("status", "=", status))
    if tag:
        filters.append(Where("tag", "=", tag))
    runs = [r for r in runs if all(f.matches(r) for f in filters)]
    runs = sort_runs(runs, sort)
    return runs[:limit] if limit else runs


def compare(idx: Index, rids: list[str]) -> dict:
    runs = [idx.run_detail(idx.resolve_id(r)) for r in rids]
    param_keys = sorted({k for r in runs for k in r["params"]})
    metric_keys = sorted({k for r in runs for k in r["metrics"]})
    params = []
    for k in param_keys:
        vals = [r["params"].get(k) for r in runs]
        params.append({"key": k, "values": vals, "differs": len({repr(v) for v in vals}) > 1})
    metrics = []
    for k in metric_keys:
        vals = [r["metrics"].get(k) for r in runs]
        metrics.append({"key": k, "values": vals})
    return {
        "runs": [{k: r[k] for k in ("id", "name", "status", "benchmark", "task", "git_sha", "created_at")} for r in runs],
        "params": params,
        "metrics": metrics,
        "artifacts": [[a["path"] for a in r["artifact_list"]] for r in runs],
    }


# ---------------------------------------------------------------- benchmarks

def load_bench_specs(project: Project) -> dict[str, dict]:
    path = project.root / BENCH_FILE
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text()).get("benchmark", {})


def set_bench_spec(project: Project, name: str, primary: str | None = None, direction: str | None = None,
                   description: str | None = None) -> dict:
    path = project.root / BENCH_FILE
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    specs = data.setdefault("benchmark", {})
    spec = specs.setdefault(name, {})
    if primary is not None:
        spec["primary"] = primary
    if direction is not None:
        if direction not in ("max", "min"):
            raise QueryError("direction must be 'max' or 'min'")
        spec["direction"] = direction
    if description is not None:
        spec["description"] = description
    path.write_text(tomli_w.dumps(data))
    return spec


def _agg(values: list[float]) -> dict:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
    return {
        "mean": statistics.fmean(vals),
        "std": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals), "max": max(vals), "n": len(vals),
    }


def leaderboard(idx: Index, project: Project, benchmark: str, group_by: str | None = None,
                status: str | None = "finished", where: list[str] | None = None) -> dict:
    spec = load_bench_specs(project).get(benchmark, {})
    primary = spec.get("primary")
    direction = spec.get("direction", "max")
    runs = list_runs(idx, benchmark=benchmark, status=status, where=where)
    metric_keys = sorted({k for r in runs for k in r["metrics"]})
    if primary and primary in metric_keys:
        metric_keys.remove(primary)
        metric_keys.insert(0, primary)
    desc = direction == "max"

    if not group_by:
        rows = sort_runs(runs, f"{'-' if desc else ''}metrics.{primary}") if primary else runs
        board = [{
            "rank": i + 1 if primary and r["metrics"].get(primary) is not None else None,
            "run": {k: r[k] for k in ("id", "name", "task", "created_at", "tags")},
            "params": r["params"],
            "metrics": r["metrics"],
        } for i, r in enumerate(rows)]
        return {"benchmark": benchmark, "spec": spec, "metrics": metric_keys, "grouped": False, "rows": board}

    fields = [f.strip() for f in group_by.split(",") if f.strip()]
    groups: dict[str, list[dict]] = {}
    for r in runs:
        key = " · ".join(str(get_field(r, f)) for f in fields)
        groups.setdefault(key, []).append(r)
    rows = []
    for g, rs in groups.items():
        stats = {k: _agg([r["metrics"].get(k) for r in rs]) for k in metric_keys}
        best = None
        if primary:
            scored = [r for r in rs if r["metrics"].get(primary) is not None]
            if scored:
                best = (max if desc else min)(scored, key=lambda r: r["metrics"][primary])["id"]
        rows.append({"group": g, "n": len(rs), "stats": stats, "best_run": best, "run_ids": [r["id"] for r in rs]})
    if primary:
        rows.sort(key=lambda row: (row["stats"][primary]["mean"] is None,
                                   -(row["stats"][primary]["mean"] or 0) if desc else (row["stats"][primary]["mean"] or 0)))
        for i, row in enumerate(rows):
            row["rank"] = i + 1 if row["stats"][primary]["mean"] is not None else None
    return {"benchmark": benchmark, "spec": spec, "metrics": metric_keys, "grouped": True, "group_by": group_by, "rows": rows}
