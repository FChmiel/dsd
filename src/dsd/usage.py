"""Claude Code usage from its local transcripts (~/.claude/projects/**/*.jsonl), for the Home page.

Only numbers are read: each reply's model, time, working folder and token counts. A reply is logged once per
content block, so replies are counted once by message id. Per-file results are cached in the dsd home by the
file's size and modification time, so only new or changed transcripts are read again.

Tokens here are input + output + cache writes; cache reads are reported separately because they dwarf the rest.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .project import ProjectNotFound, dsd_home, find_project

CACHE_VERSION = 2


def transcripts_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def cache_file() -> Path:
    return dsd_home() / "cache" / "claude-usage.json"


def _scan(path: Path) -> dict:
    """{'rows': {'date|model|cwd': [tokens, output, cache_read, messages]}, 'sessions': [[date, session], ...]}"""
    rows: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    sessions: set[tuple[str, str]] = set()
    seen: set[str] = set()
    with open(path, "rb") as fh:
        for raw in fh:
            if b'"assistant"' not in raw or b'"usage"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage") or {}
            if d.get("type") != "assistant" or not u or not d.get("timestamp") or msg.get("model") == "<synthetic>":
                continue
            key = f"{msg.get('id')}|{d.get('requestId')}"
            if key in seen:
                continue
            seen.add(key)
            try:
                day = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone().date().isoformat()
            except ValueError:
                continue
            tokens = int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
            row = rows[f"{day}|{msg.get('model') or 'unknown'}|{d.get('cwd') or ''}"]
            row[0] += tokens
            row[1] += int(u.get("output_tokens") or 0)
            row[2] += int(u.get("cache_read_input_tokens") or 0)
            row[3] += 1
            if d.get("sessionId"):
                sessions.add((day, d["sessionId"]))
    return {"rows": dict(rows), "sessions": sorted(sessions)}


def _load_cache() -> dict:
    try:
        cache = json.loads(cache_file().read_text())
        return cache if cache.get("version") == CACHE_VERSION else {}
    except (FileNotFoundError, ValueError):
        return {}


def _project_name(cwd: str, names: dict[str, tuple[str, str | None]]) -> tuple[str, str | None]:
    if cwd not in names:
        try:
            p = find_project(Path(cwd)) if cwd else None
            names[cwd] = (p.name, p.id) if p else ("other", None)
        except (ProjectNotFound, OSError):
            names[cwd] = ("other", None)
    return names[cwd]


def claude_usage(days: int = 182, recent: int = 30) -> dict:
    """Daily usage for the last `days` days, and totals by model and dsd project for the last `recent` days."""
    root = transcripts_dir()
    today = date.today()
    first = (today - timedelta(days=days - 1)).isoformat()
    since_recent = (today - timedelta(days=recent - 1)).isoformat()
    cutoff = datetime.combine(today - timedelta(days=days), datetime.min.time()).timestamp()
    cache = _load_cache()
    files: dict = {}
    for path in root.rglob("*.jsonl") if root.is_dir() else []:
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime < cutoff:
            continue
        prior = (cache.get("files") or {}).get(str(path))
        if prior and prior["mtime"] == st.st_mtime and prior["size"] == st.st_size:
            files[str(path)] = prior
        else:
            try:
                files[str(path)] = {"mtime": st.st_mtime, "size": st.st_size, **_scan(path)}
            except OSError:
                continue
    try:
        cache_file().parent.mkdir(parents=True, exist_ok=True)
        cache_file().write_text(json.dumps({"version": CACHE_VERSION, "files": files}))
    except OSError:
        pass

    day_totals: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "output": 0, "messages": 0, "sessions": 0})
    day_sessions: dict[str, set] = defaultdict(set)
    models: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "messages": 0})
    projects: dict[tuple[str, str | None], int] = defaultdict(int)
    totals = {"tokens": 0, "output": 0, "cache_read": 0, "messages": 0, "sessions": 0}
    recent_sessions: set[str] = set()
    names: dict[str, tuple[str, str | None]] = {}
    for f in files.values():
        for key, (tokens, output, cache_read, messages) in f["rows"].items():
            day, model, cwd = key.split("|", 2)
            if day < first:
                continue
            t = day_totals[day]
            t["tokens"] += tokens
            t["output"] += output
            t["messages"] += messages
            if day >= since_recent:
                totals["tokens"] += tokens
                totals["output"] += output
                totals["cache_read"] += cache_read
                totals["messages"] += messages
                models[model]["tokens"] += tokens
                models[model]["messages"] += messages
                projects[_project_name(cwd, names)] += tokens
        for day, session in f["sessions"]:
            if day >= first:
                day_sessions[day].add(session)
            if day >= since_recent:
                recent_sessions.add(session)
    for day, ids in day_sessions.items():
        day_totals[day]["sessions"] = len(ids)
    totals["sessions"] = len(recent_sessions)
    return {
        "from": first, "to": today.isoformat(), "recent_days": recent,
        "days": dict(sorted(day_totals.items())),
        "totals": totals,
        "models": [{"model": m, **v} for m, v in sorted(models.items(), key=lambda kv: (-kv[1]["tokens"], kv[0]))],
        "projects": [{"project": n, "project_id": pid, "tokens": t}
                     for (n, pid), t in sorted(projects.items(), key=lambda kv: (-kv[1], kv[0][0]))],
    }
