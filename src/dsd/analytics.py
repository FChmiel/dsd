"""Analytics: short posts of key results, kept in the project's docs under analytics/.

Each post is markdown with frontmatter (title, date, headline, metrics, and links to the task, plan,
benchmark and runs it comes from), so the app can show them as cards and anyone can read them as files.
"""

from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime
from pathlib import Path

import yaml

from .project import Project

FOLDER = "analytics"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "result"


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end():]


def list_posts(project: Project) -> list[dict]:
    folder = project.docs_path / FOLDER
    if not folder.is_dir():
        return []
    posts = []
    for f in folder.glob("*.md"):
        meta, body = _split(f.read_text(errors="replace"))
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        mtime = f.stat().st_mtime
        posts.append({
            "path": f"{FOLDER}/{f.name}",
            "title": str(meta.get("title") or (heading.group(1).strip() if heading else f.stem)),
            "date": str(meta.get("date") or datetime.fromtimestamp(mtime).date().isoformat()),
            "headline": str(meta.get("headline") or ""),
            "metrics": dict(meta.get("metrics") or {}),
            "task": meta.get("task"), "plan": meta.get("plan"), "benchmark": meta.get("benchmark"),
            "runs": list(meta.get("runs") or []), "mtime": mtime,
        })
    posts.sort(key=lambda p: (p["date"], p["mtime"]), reverse=True)
    return posts


def write_post(project: Project, title: str, headline: str, body: str, *, metrics: dict | None = None,
               task: str | None = None, plan: str | None = None, benchmark: str | None = None,
               runs: list[str] | None = None, date: str | None = None) -> str:
    """Write a result post; returns its path relative to the docs folder."""
    day = date or _date.today().isoformat()
    _date.fromisoformat(day)
    folder = project.docs_path / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    name, n = f"{day}-{_slug(title)}", 1
    while (folder / f"{name}.md").exists():
        n += 1
        name = f"{day}-{_slug(title)}-{n}"
    meta = {"title": title, "date": day, "headline": headline}
    meta.update({k: v for k, v in {"metrics": metrics, "task": task, "plan": plan, "benchmark": benchmark,
                                   "runs": runs}.items() if v})
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    Path(folder / f"{name}.md").write_text(f"---\n{front}---\n\n# {title}\n\n**{headline}**\n\n{body.strip()}\n")
    return f"{FOLDER}/{name}.md"
