"""dsd MCP server (stdio): plans, docs and experiment runs for agents.

Registered user-wide by `dsd setup`; Claude Code launches it in the repo it is working in, and it finds
that repo's dsd project (override with DSD_PROJECT_ROOT).
Every tool is a thin wrapper over the same functions the CLI and the app use.
"""

from __future__ import annotations

import functools
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import docs as docs_mod
from . import plans
from .project import ProjectNotFound, current_project
from .tracking.index import Index
from .tracking.query import QueryError, compare, leaderboard, list_runs, load_bench_specs

INSTRUCTIONS = """\
dsd manages plans, docs and experiment runs for the repo you are working in. Its state lives outside the repo,
in the project's data dir (~/.dsd/projects/<id>/, shown by project_overview). Never create dsd files in the repo.
- Start with project_overview. If there is no project for this repo, the user can start one with `dsd init`.
- Plans: the central plan is "main"; sub-plans have their own slugs (plan_list, plan_read). Task ids (T-12) are
  unique across all plans. Markers: [ ] todo, [/] doing, [x] done, [!] blocked, [-] dropped.
- Change task status with task_update (or `dsd task start|done|block T-12`) rather than editing plan files by hand.
- Docs: use docs_list, docs_search, docs_read and docs_write with paths relative to the docs folder. Decisions go
  in decisions/, notes in notes/, HTML reports in reports/.
- Tag experiment runs with the task they serve: dsd.run(..., task="T-12") or `dsd exec --task T-12 -- <cmd>`.
  Query them with runs_query, run_get, runs_compare and bench_board.
- Add a `Task: T-12` trailer to commits that implement a task.
- You may be in a dsd git worktree (branch dsd/<name>). Commit your work on that branch; the user reviews and
  merges it from the dsd app (`dsd wt merge`). Plans, docs and runs are shared with the main checkout.
- Review comments the user left in the dsd app: review_comments, then review_resolve once addressed.
"""

server = MCPServer(name="dsd", instructions=INSTRUCTIONS)

_EXPECTED = (docs_mod.DocsError, plans.PlanError, QueryError, ProjectNotFound, KeyError, ValueError, FileNotFoundError)


def tool(fn):
    """Register an MCP tool; expected failures become clean tool errors instead of server crashes."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _EXPECTED as e:
            raise ToolError(str(e.args[0]) if e.args else str(e)) from e

    return server.tool()(wrapper)


def _project():
    try:
        return current_project()
    except ProjectNotFound as e:
        raise ValueError(str(e)) from e


def _compact_run(r: dict, metric_keys: list[str] | None = None) -> dict:
    metrics = r["metrics"] if not metric_keys else {k: r["metrics"].get(k) for k in metric_keys}
    return {
        "id": r["id"], "name": r["name"], "status": r["status"], "benchmark": r["benchmark"], "task": r["task"],
        "created_at": r["created_at"], "params": r["params"], "metrics": metrics, "tags": r["tags"],
        "artifacts": r["artifacts"],
    }


@tool
def project_overview() -> dict:
    """Project summary: plans with task counts, tasks in progress, benchmarks and the 10 most recent runs."""
    p = _project()
    all_plans = plans.load_plans(p)
    with Index(p) as idx:
        idx.sync()
        recent = list_runs(idx, limit=10)
        benches = idx.benchmarks()
    return {
        "project": {"name": p.name, "id": p.id, "root": str(p.root), "repo": str(p.repo), "scope": p.scope,
                    "data_dir": str(p.data_dir)},
        "plans": [{"slug": pl.slug, "title": pl.title, **pl.counts()} for pl in all_plans],
        "in_progress": [t.to_dict() for pl in all_plans for t in pl.tasks if t.status == "doing"],
        "benchmarks": benches,
        "recent_runs": [_compact_run(r) for r in recent],
    }


@tool
def plan_list() -> list[dict]:
    """List the project's plans (main first) with task counts by status."""
    p = _project()
    return [{"slug": pl.slug, "title": pl.title, "status": pl.meta.get("status", "active"), **pl.counts()}
            for pl in plans.load_plans(p)]


@tool
def plan_read(slug: str = "main") -> dict:
    """Read a plan: its raw markdown plus parsed tasks (id, status, title, tags, attrs, parent, notes)."""
    p = _project()
    pl = plans.load_plan(p, slug)
    return {"slug": pl.slug, "title": pl.title, "meta": pl.meta, "markdown": "".join(pl.lines),
            "tasks": [t.to_dict() for t in pl.tasks]}


@tool
def task_add(title: str, plan: str = "main", tags: list[str] | None = None, attrs: dict[str, str] | None = None,
             parent: str | None = None, section: str = "Tasks") -> dict:
    """Add a task to a plan (default: the central plan's 'Tasks' section). Returns the task with its new id."""
    p = _project()
    return plans.add_task(p, title, plan, tags, attrs, plans.normalize_id(parent) if parent else None, section).to_dict()


@tool
def task_update(task_id: str, status: str | None = None, note: str | None = None) -> dict:
    """Change a task's status (todo, doing, done, blocked, dropped) and/or append a note line under it."""
    p = _project()
    pl, t = plans.find_task(p, task_id)
    if status:
        plans.set_status(pl, t, status)
    if note:
        plans.append_note(pl, t, note)
    pl.save()
    return plans.find_task(p, t.id)[1].to_dict()


@tool
def task_delete(task_id: str) -> str:
    """Delete a task with its notes and subtasks. Prefer task_update(status="dropped") to keep the history;
    delete only when the user asks."""
    return "deleted " + ", ".join(plans.remove_task(_project(), task_id))


@tool
def docs_list() -> list[dict]:
    """List files in the project's docs folder (paths relative to docs/)."""
    return docs_mod.list_docs(_project())


@tool
def docs_search(query: str, limit: int = 10) -> list[dict]:
    """Full-text search over project docs (markdown and HTML). All words must match."""
    return docs_mod.search(_project(), query, limit)


@tool
def docs_read(path: str) -> str:
    """Read a doc by path relative to docs/ (e.g. 'plans/main.md', 'decisions/0001-x.md')."""
    return docs_mod.read_doc(_project(), path)


@tool
def docs_write(path: str, content: str) -> str:
    """Create or overwrite a doc under docs/ (.md, .html, .txt, .yaml, .json, .csv). Prefer task_update for plan status."""
    p = _project()
    written = docs_mod.write_doc(p, path, content)
    return f"wrote {written}"


@tool
def runs_query(benchmark: str | None = None, task: str | None = None, status: str | None = None,
               tag: str | None = None, where: list[str] | None = None, sort: str | None = None,
               metrics: list[str] | None = None, limit: int = 20) -> list[dict]:
    """Query experiment runs. `where` items look like 'metrics.auc>=0.8', 'params.model.type=xgb', 'name~baseline'.
    `sort` like '-metrics.auc' (descending). `metrics` limits which metric values are returned."""
    p = _project()
    with Index(p) as idx:
        idx.sync()
        rows = list_runs(idx, benchmark=benchmark, task=plans.normalize_id(task) if task else None,
                         status=status, tag=tag, where=where, sort=sort, limit=limit)
    return [_compact_run(r, metrics) for r in rows]


@tool
def run_get(run_id: str) -> dict:
    """Full details for one run (id or unique suffix): params, metric stats, info, datasets, git, artifacts."""
    p = _project()
    with Index(p) as idx:
        idx.sync()
        d = idx.run_detail(idx.resolve_id(run_id))
    d.pop("meta", None)
    return d


@tool
def run_add(name: str, benchmark: str | None = None, metrics: dict[str, float] | None = None,
            task: str | None = None, params: dict | None = None, links: dict[str, str] | None = None,
            artifacts: list[str] | None = None, notes: str | None = None, created_at: str | None = None,
            commit: str | None = None) -> dict:
    """Record a run that already happened, e.g. a benchmark whose results were dumped to an HTML file.
    metrics: numbers to compare on the benchmark. links: label -> URL (S3, dashboards, PRs).
    artifacts: file or folder paths to copy into the run. created_at: ISO date/time of the run. commit: git ref it ran from.
    Confirm the benchmark, metrics and links with the user before calling."""
    from .tracking.record import record_run

    p = _project()
    b = record_run(p, name, benchmark=benchmark, task=plans.normalize_id(task) if task else None, metrics=metrics,
                   params=params, links=links, artifacts=artifacts, notes=notes, created_at=created_at, commit=commit)
    with Index(p) as idx:
        idx.sync()
        d = idx.run_detail(b.id)
    d.pop("meta", None)
    return d


@tool
def runs_compare(run_ids: list[str]) -> dict:
    """Compare runs side by side: params (with a 'differs' flag) and metrics."""
    p = _project()
    with Index(p) as idx:
        idx.sync()
        return compare(idx, run_ids)


@tool
def bench_list() -> list[dict]:
    """List benchmarks with run counts and their ranking spec (primary metric, direction) if set."""
    p = _project()
    specs = load_bench_specs(p)
    with Index(p) as idx:
        idx.sync()
        benches = idx.benchmarks()
    names = {b["name"] for b in benches}
    return [{**b, "spec": specs.get(b["name"], {})} for b in benches] + \
        [{"name": n, "runs": 0, "spec": s} for n, s in specs.items() if n not in names]


@tool
def bench_board(benchmark: str, group_by: str | None = None, where: list[str] | None = None) -> dict:
    """Leaderboard for a benchmark. group_by (e.g. 'params.model.type') aggregates mean/std across seeds."""
    p = _project()
    with Index(p) as idx:
        idx.sync()
        return leaderboard(idx, p, benchmark, group_by=group_by, where=where)


@tool
def artifact_get(run_id: str, path: str, max_chars: int = 20000) -> dict:
    """Get an artifact's absolute path and metadata; text artifacts (HTML, CSV, JSON...) include content."""
    p = _project()
    with Index(p) as idx:
        idx.sync()
        d = idx.run_detail(idx.resolve_id(run_id))
    meta = next((a for a in d["artifact_list"] if a["path"] == path), None)
    if meta is None:
        raise ValueError(f"No artifact '{path}' in run {d['id']}")
    full = Path(d["bundle_path"]) / "artifacts" / path
    out = {**meta, "abs_path": str(full)}
    if (meta.get("mime") or "").startswith(("text/", "application/json")):
        text = full.read_text(errors="replace")
        out["content"] = text[:max_chars]
        out["truncated"] = len(text) > max_chars
    return out


@tool
def review_comments(status: str = "open") -> list[dict]:
    """Review comments the user left on diffs in the dsd app (status: open, sent, resolved, or all)."""
    from . import review

    cs = review.load_comments(_project())
    return cs if status == "all" else [c for c in cs if c["status"] == status]


@tool
def review_resolve(comment_ids: list[str]) -> str:
    """Mark review comments as resolved after addressing them."""
    from . import review

    p = _project()
    for cid in comment_ids:
        review.update_comment(p, cid, status="resolved")
    return f"resolved {len(comment_ids)} comment(s)"


@tool
def todo_add(text: str, due: str | None = None, project: str | None = None) -> dict:
    """Add a personal to-do to the user's dsd Home (cross-project), e.g. 'Send David the AUC numbers'.
    Dates in the text are understood ('tomorrow', 'fri', 'next week', '11/14'); or pass due as YYYY-MM-DD.
    project: a registered dsd project name (defaults to none; '#name' in the text also works)."""
    from . import home

    return home.add_todo(text, due, project)


@tool
def todo_list() -> list[dict]:
    """The user's personal to-dos from dsd Home (open ones plus those completed today), with due dates."""
    from . import home

    return home.list_todos()


@tool
def todo_update(task_id: str, status: str | None = None, due: str | None = None, title: str | None = None,
                project: str | None = None) -> dict:
    """Edit a Home to-do. status: todo/doing/done/dropped. due: YYYY-MM-DD, or 'none' to clear.
    title: new text. project: a registered dsd project name, or 'none' to clear. Omitted fields are unchanged."""
    from . import home

    keep = "__keep__"
    return home.update_todo(
        task_id, status,
        keep if due is None else (None if due == "none" else due),
        title,
        keep if project is None else (None if project == "none" else project),
    )


@tool
def todo_delete(task_id: str) -> str:
    """Delete a Home to-do (prefer todo_update(status='done' or 'dropped') to keep history)."""
    from . import home

    home.delete_todo(task_id)
    return f"deleted {task_id}"


def main() -> None:
    server.run("stdio")
