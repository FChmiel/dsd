"""Home: the cross-project command centre.

Personal to-dos ("Send David the AUC numbers tomorrow #churn-model") live in a plain markdown checklist at
~/.dsd/home/docs/plans/main.md, using the same task syntax as project plans:

    - [ ] T-7 Send David the AUC numbers @due:2026-11-11 @project:churn-model

The dashboard combines those with every registered project's plan tasks (including ones with @due:YYYY-MM-DD),
blocked work, worktrees, runs, review comments and recently edited docs.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import plans, registry, review
from .project import Project

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = {d: i for i, d in enumerate(DAYS)} | {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "tues": 1, "thur": 3, "thurs": 3,
}

INBOX_TEMPLATE = """---
title: Home
status: active
---

# Home

Personal to-dos across projects. Managed by dsd (Home page, `dsd todo`, MCP `todo_*` tools), but plain markdown:
edit freely. Syntax: `- [ ] T-1 Send David the numbers @due:2026-11-11 @project:churn-model`

## Tasks

"""


# ---------------------------------------------------------------- storage

def home_project() -> Project:
    root = registry.home() / "home"
    p = Project(root=root, id="home", name="Home", docs_dir="docs")
    if not p.main_plan_path.exists():
        p.main_plan_path.parent.mkdir(parents=True, exist_ok=True)
        p.main_plan_path.write_text(INBOX_TEMPLATE)
    return p


# ---------------------------------------------------------------- quick-add parsing

def _next_weekday(today: date, wd: int) -> date:
    return today + timedelta(days=(wd - today.weekday()) % 7 or 7)


def parse_due(text: str, today: date | None = None) -> tuple[str, date | None]:
    """Pull a day out of free text. Returns (text without the date words, date or None).

    Understands: today, tonight, tomorrow/tmr/tmrw, yesterday, mon..sun (next occurrence; 'next fri' = the one after),
    next week (Monday), this weekend (Saturday), in N days/weeks, YYYY-MM-DD, MM/DD, DD Mon / Mon DD.
    """
    today = today or date.today()
    s = f" {text.strip()} "
    found: date | None = None

    def take(pattern: str, fn):
        nonlocal s, found
        if found is not None:
            return
        m = re.search(pattern, s, flags=re.IGNORECASE)
        if not m:
            return
        d = fn(m)
        if d is None:
            return
        found = d
        s = s[: m.start()] + " " + s[m.end():]

    take(r"\s(?:@|due:?\s*)?(\d{4}-\d{2}-\d{2})(?=\s)", lambda m: _safe_date(*map(int, m.group(1).split("-"))))
    take(r"\s(?:on\s+|by\s+|due\s+)?(today|tonight|eod)(?=\s)", lambda m: today)
    take(r"\s(?:on\s+|by\s+|due\s+)?(tomorrow|tmrw?|tmr)(?=\s)", lambda m: today + timedelta(days=1))
    take(r"\s(?:on\s+|by\s+|due\s+|since\s+)?(yesterday)(?=\s)", lambda m: today - timedelta(days=1))
    take(r"\s(?:on\s+|by\s+)?next\s+week(?=\s)", lambda m: today + timedelta(days=7 - today.weekday()))
    take(r"\s(?:on\s+|by\s+)?this\s+weekend(?=\s)", lambda m: _next_weekday(today, 5) if today.weekday() != 5 else today)
    take(r"\sin\s+(\d+)\s+(day|days|week|weeks)(?=\s)",
         lambda m: today + timedelta(days=int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)))
    take(r"\s(?:on\s+|by\s+)?(next\s+)?(mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)(?=\s)",
         lambda m: _weekday(today, DAY_NAMES[m.group(2).lower()], bool(m.group(1))))
    take(r"\s(?:on\s+|by\s+)?(\d{1,2})/(\d{1,2})(?=\s)", lambda m: _future(today, int(m.group(1)), int(m.group(2))))
    take(r"\s(?:on\s+|by\s+)?(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?=\s)",
         lambda m: _future(today, _month(m.group(2)), int(m.group(1))))
    take(r"\s(?:on\s+|by\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?=\s)",
         lambda m: _future(today, _month(m.group(1)), int(m.group(2))))
    return " ".join(s.split()), found


def _weekday(today: date, wd: int, nxt: bool) -> date:
    delta = (wd - today.weekday()) % 7 or 7  # "fri" on a Friday means next Friday
    if nxt and delta < 7:
        delta += 7
    return today + timedelta(days=delta)


def _month(name: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(name[:3].lower()) + 1


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _future(today: date, month: int, day: int) -> date | None:
    d = _safe_date(today.year, month, day)
    if d is None:
        return None
    if d < today - timedelta(days=30):  # "1/5" in December means next January
        d = _safe_date(today.year + 1, month, day)
    return d


def parse_quick(text: str, project_names: list[str], today: date | None = None) -> dict:
    """'Send David the numbers tomorrow #churn-model #email' -> title, due, project, tags."""
    rest, due = parse_due(text, today)
    lowered = {n.lower(): n for n in project_names}
    project, tags = None, []
    for tag in re.findall(r"(?:^|\s)#([\w\-./]+)", rest):
        if tag.lower() in lowered and project is None:
            project = lowered[tag.lower()]
        else:
            tags.append(tag)
    title = re.sub(r"(?:^|\s)#[\w\-./]+", "", rest).strip()
    return {"title": title or text.strip(), "due": due.isoformat() if due else None, "project": project, "tags": tags}


# ---------------------------------------------------------------- todos

def _todo_dict(t: plans.Task, source: str = "home", project: Project | None = None) -> dict:
    return {
        "id": t.id, "title": t.title, "status": t.status, "due": t.attrs.get("due"), "tags": t.tags,
        "project": t.attrs.get("project") if source == "home" else (project.name if project else None),
        "project_id": project.id if project else None, "source": source, "plan": t.plan, "notes": t.notes,
    }


def list_todos(include_done_days: int = 1) -> list[dict]:
    hp = home_project()
    cutoff = (date.today() - timedelta(days=include_done_days)).isoformat()
    out = []
    for t in plans.load_plan(hp).tasks:
        if not t.id:
            continue
        if t.status in ("done", "dropped") and (t.attrs.get("done") or "") < cutoff:
            continue
        out.append(_todo_dict(t))
    return out


def add_todo(text: str, due: str | None = None, project: str | None = None) -> dict:
    hp = home_project()
    names = [p.name for p in registry.projects()]
    q = parse_quick(text, names)
    attrs = {}
    if due or q["due"]:
        attrs["due"] = due or q["due"]
    if project or q["project"]:
        attrs["project"] = project or q["project"]
    t = plans.add_task(hp, q["title"], tags=q["tags"], attrs=attrs)
    return _todo_dict(t)


def update_todo(task_id: str, status: str | None = None, due: str | None = "__keep__",
                title: str | None = None, project: str | None = "__keep__") -> dict:
    hp = home_project()
    pl, t = plans.find_task(hp, task_id)
    if status:
        plans.set_status(pl, t, status)
        plans.set_attr(pl, t, "done", date.today().isoformat() if status in ("done", "dropped") else None)
    if due != "__keep__":
        if due:
            date.fromisoformat(due)  # validate
        plans.set_attr(pl, t, "due", due or None)
    if project != "__keep__":
        plans.set_attr(pl, t, "project", project or None)
    if title:
        plans.set_title(pl, t, title)
    pl.save()
    return _todo_dict(plans.find_task(hp, t.id)[1])


def delete_todo(task_id: str) -> None:
    hp = home_project()
    pl, t = plans.find_task(hp, task_id)
    plans.delete_task(pl, t)
    pl.save()


# ---------------------------------------------------------------- dashboard

def _recent_docs(p: Project, days: int = 14, limit: int = 6) -> list[dict]:
    if not p.docs_path.is_dir():
        return []
    cutoff = time.time() - days * 86400
    items = []
    for f in p.docs_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".md", ".html") and not f.name.startswith("."):
            mt = f.stat().st_mtime
            if mt >= cutoff and "plans/" not in f.relative_to(p.docs_path).as_posix():
                items.append({"path": f.relative_to(p.docs_path).as_posix(), "mtime": mt})
    items.sort(key=lambda x: -x["mtime"])
    return items[:limit]


def project_summary(p: Project, terminals: list[dict] | None = None) -> dict:
    from .tracking.index import Index
    from .tracking.query import list_runs

    all_plans = plans.load_plans(p)
    tasks = [t for pl in all_plans for t in pl.tasks if t.id]
    doing = [t.to_dict() for t in tasks if t.status == "doing"]
    blocked = [t.to_dict() for t in tasks if t.status == "blocked"]
    dated = [_todo_dict(t, "project", p) for t in tasks if t.attrs.get("due") and t.status in plans.OPEN_STATUSES]
    counts = {s: sum(1 for t in tasks if t.status == s) for s in ("todo", "doing", "blocked", "done")}

    since = (datetime.now().astimezone() - timedelta(hours=24)).isoformat()
    try:
        with Index(p) as idx:
            idx.sync()
            runs = list_runs(idx, limit=200)
    except Exception:
        runs = []
    recent = [r for r in runs if (r["created_at"] or "") >= since]
    failed = [r for r in recent if r["status"] in ("failed", "crashed")]
    running = [r for r in runs if r["status"] == "running"]

    wts = []
    if review.is_repo(p.root):
        from .worktrees import list_worktrees

        try:
            for w in list_worktrees(p):
                if w["is_main"]:
                    continue
                sessions = [t for t in (terminals or []) if t.get("worktree") == w["name"] and not t.get("exited")]
                wts.append({"name": w["name"], "branch": w["branch"], "ahead": w.get("ahead"), "dirty": w.get("dirty"),
                            "task": w.get("task"), "sessions": len(sessions)})
        except Exception:
            pass
    comments = [c for c in review.load_comments(p) if c["status"] == "open"]
    return {
        "id": p.id, "name": p.name, "root": str(p.root), "counts": counts, "doing": doing, "blocked": blocked,
        "dated": dated, "runs_24h": len(recent), "failed_24h": [{"id": r["id"], "name": r["name"]} for r in failed],
        "running": [{"id": r["id"], "name": r["name"]} for r in running],
        "last_run": ({"id": runs[0]["id"], "name": runs[0]["name"], "status": runs[0]["status"],
                      "created_at": runs[0]["created_at"], "metrics": runs[0]["metrics"]} if runs else None),
        "worktrees": wts, "open_comments": len(comments), "recent_docs": _recent_docs(p),
        "sessions": sum(1 for t in (terminals or []) if not t.get("exited")),
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def dashboard(terminals_by_project: dict[str, list[dict]] | None = None) -> dict:
    today = date.today()
    todos = list_todos()
    projects = []
    for p in registry.projects():
        try:
            projects.append(project_summary(p, (terminals_by_project or {}).get(p.id, [])))
        except Exception as e:  # one broken project shouldn't blank the home page
            projects.append({"id": p.id, "name": p.name, "root": str(p.root), "error": str(e)})

    agenda = [t for t in todos] + [t for pr in projects for t in pr.get("dated", [])]
    open_items = [t for t in agenda if t["status"] in plans.OPEN_STATUSES]
    overdue = [t for t in open_items if t["due"] and t["due"] < today.isoformat()]
    due_today = [t for t in open_items if t["due"] == today.isoformat()]

    attention = []
    for pr in projects:
        if pr.get("error"):
            attention.append({"kind": "error", "project": pr["name"], "project_id": pr["id"], "text": pr["error"]})
            continue
        for t in pr["blocked"]:
            attention.append({"kind": "blocked", "project": pr["name"], "project_id": pr["id"], "task": t["id"],
                              "text": f"{t['id']} blocked: {t['title']}"})
        for w in pr["worktrees"]:
            if w["ahead"] and not w["dirty"]:
                attention.append({"kind": "merge", "project": pr["name"], "project_id": pr["id"], "worktree": w["name"],
                                  "text": f"worktree {w['name']} has {_plural(w['ahead'], 'commit')} ready to merge"})
            elif w["dirty"] and not w["sessions"]:
                attention.append({"kind": "uncommitted", "project": pr["name"], "project_id": pr["id"], "worktree": w["name"],
                                  "text": f"worktree {w['name']} has {_plural(w['dirty'], 'uncommitted change')} and no open session"})
        for r in pr["failed_24h"]:
            attention.append({"kind": "failed", "project": pr["name"], "project_id": pr["id"], "run": r["id"],
                              "text": f"run {r['name']} failed"})
        if pr["open_comments"]:
            attention.append({"kind": "comments", "project": pr["name"], "project_id": pr["id"],
                              "text": f"{_plural(pr['open_comments'], 'review comment')} not sent to an agent"})

    parts = []
    if due_today or overdue:
        parts.append(f"{_plural(len(due_today), 'thing')} due today" + (f", {len(overdue)} overdue" if overdue else ""))
    else:
        parts.append("Nothing due today")
    doing = sum(len(pr.get("doing", [])) for pr in projects)
    if doing:
        parts.append(f"{_plural(doing, 'task')} in progress across {_plural(sum(1 for pr in projects if pr.get('doing')), 'project')}")
    runs = sum(pr.get("runs_24h", 0) for pr in projects)
    if runs:
        parts.append(f"{_plural(runs, 'run')} in the last 24h")
    if attention:
        parts.append(f"{_plural(len(attention), 'item')} need you")

    return {
        "today": today.isoformat(), "weekday": DAYS[today.weekday()], "summary": " · ".join(parts),
        "todos": todos, "agenda": agenda, "attention": attention, "projects": projects,
        "counts": {"overdue": len(overdue), "today": len(due_today), "open": len(open_items)},
    }
