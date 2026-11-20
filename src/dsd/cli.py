"""`dsd` command-line interface."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from . import plans
from .init import init_project
from .plans import PlanError, Task
from .project import ProjectNotFound, current_project, find_project

app = typer.Typer(no_args_is_help=True, add_completion=False, help="dsd: plans, docs and experiment tracking.")
console = Console()
err = Console(stderr=True)

_STYLE = {"created": "green", "updated": "yellow", "unchanged": "dim"}


def _project():
    try:
        return current_project()
    except ProjectNotFound as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Print the dsd version."""
    console.print(__version__)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Repo (or any folder) the project is for (default: current directory)."),
    name: str = typer.Option(None, "--name", "-n", help="Project name (default: repo or scope directory name)."),
    scope: str = typer.Option(None, "--scope", "-s", help="Repo-relative subdirectory the project covers (default: the whole repo)."),
) -> None:
    """Start a dsd project for a repo. Its docs, plans and runs live in ~/.dsd/projects/<id>/; nothing is written to the repo."""
    try:
        report = init_project(path, name=name, scope=scope)
    except ValueError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    for action, rel in report.actions:
        if action != "unchanged":
            console.print(f"  [{_STYLE[action]}]{action:9}[/] {rel}")
    p = report.project
    where = f"{p.repo}" + (f" (scope {p.scope})" if p.scope else "")
    if report.changed:
        console.print(f"[bold]dsd project '{p.name}'[/] for {where}  (id {p.id})")
        console.print(f"  data   {p.data_dir}")
    else:
        console.print(f"dsd project '{p.name}' for {where} already up to date.")


def _repo_project(p, ref: str):
    from .project import repo_projects

    found = next((x for x in repo_projects(p.repo) if ref in (x.name, x.id)), None)
    if found is None:
        err.print(f"[red]No project '{ref}' on {p.repo}[/red]")
        raise typer.Exit(1)
    return found


@app.command("default")
def default_(name: str = typer.Argument(None, help="Project to make the default (name or id).")) -> None:
    """Show or set the repo's default project: the one its main checkout resolves to."""
    from .init import set_default
    from .project import pick_default, repo_projects

    p = _project()
    if name:
        set_default(_repo_project(p, name))
    same = repo_projects(p.repo, p.scope)
    d = pick_default(same)
    for x in same:
        console.print(f"{'★' if x.id == d.id else ' '} [bold]{x.name}[/]  [dim]{x.id}[/]")


@app.command("projects")
def projects_(archived: bool = typer.Option(False, "--archived", "-a", help="Also list archived projects.")) -> None:
    """List dsd projects (name, repo, scope)."""
    from .project import all_projects

    for p in all_projects(include_archived=archived):
        where = f"{p.repo}" + (f"/{p.scope}" if p.scope else "")
        console.print(f"  [bold]{p.name:<24}[/] {where}" + ("  [yellow]archived[/]" if p.archived else ""))


@app.command("archive")
def archive_(
    name: str = typer.Argument(None, help="Project name or id (default: the current project)."),
    force: bool = typer.Option(False, "--force", "-f", help="Discard uncommitted changes in its worktrees."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Archive without asking."),
) -> None:
    """Archive a project: hide it and remove its dsd worktrees (branches, docs and runs are kept)."""
    from . import archive as ar

    p = _project() if not name else _any_project(name)
    pv = ar.preview(p)
    if not yes:
        console.print(f"Archiving [bold]{p.name}[/] would:")
        for w in pv["remove"]:
            console.print(f"  remove worktree {w['name']} [dim](branch {w['branch']} is kept)[/]"
                          + (f"  [red]{w['dirty']} uncommitted change(s)[/]" if w["dirty"] else ""))
        for w in pv["unlist"]:
            console.print(f"  stop listing adopted worktree {w['name']} [dim](not deleted)[/]")
        console.print("  keep its docs, plans and runs. Re-run with --yes to archive.")
        raise typer.Exit(1)
    try:
        r = ar.archive_project(p, force=force)
    except ar.ArchiveError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]archived[/] {p.name}" + (f", removed {', '.join(r['removed'])}" if r["removed"] else "")
                  + f"  [dim](dsd restore {p.name})[/]")


@app.command("restore")
def restore_(name: str = typer.Argument(..., help="Archived project name or id.")) -> None:
    """Restore an archived project and recreate its worktrees from their branches."""
    from . import archive as ar

    p = _any_project(name)
    if not p.archived:
        err.print(f"[red]'{p.name}' isn't archived[/red]")
        raise typer.Exit(1)
    r = ar.restore_project(p)
    console.print(f"[green]restored[/] {p.name}" + (f" with {', '.join(r['restored'])}" if r["restored"] else "")
                  + (f"  [yellow]branch gone for {', '.join(r['missing'])}[/]" if r["missing"] else ""))


def _any_project(ref: str):
    from .project import all_projects

    matches = [p for p in all_projects(include_archived=True) if ref in (p.name, p.id)]
    if len(matches) != 1:
        err.print(f"[red]{'No' if not matches else 'More than one'} project '{ref}'[/red]"
                  + (" (use its id; see `dsd projects -a`)" if matches else ""))
        raise typer.Exit(1)
    return matches[0]


@app.command()
def setup(force: bool = typer.Option(False, "--force", help="Overwrite dsd skills you have edited.")) -> None:
    """Wire dsd into Claude Code for your user: register the dsd MCP server and install the dsd skills."""
    from . import agents

    for action, path in agents.install_skills(force=force):
        if action != "unchanged":
            style = "yellow" if action == "kept" else _STYLE[action]
            hint = "  [dim](you edited it; --force to replace)[/]" if action == "kept" else ""
            console.print(f"  [{style}]{action:9}[/] {path}{hint}")
    try:
        mcp = agents.register_mcp()
    except RuntimeError as e:
        err.print(f"[red]Could not register the MCP server: {e}[/red]")
        raise typer.Exit(1)
    if mcp == "missing":
        err.print("[yellow]The claude CLI isn't on your PATH.[/] Register the MCP server yourself with:\n  "
                  + " ".join(agents.mcp_add_command()), soft_wrap=True)
        raise typer.Exit(1)
    if mcp in ("created", "updated"):
        console.print(f"  [green]{mcp:9}[/] MCP server 'dsd' (user scope) → {' '.join(agents.mcp_command())}")
    console.print("dsd is set up for Claude Code. Start a project in a repo with `dsd init`.")


@app.command()
def ui(
    port: int = typer.Option(8765, "--port"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't open a browser."),
    project_path: Path = typer.Argument(None, help="Project to open (default: current project, if any)."),
) -> None:
    """Start the dsd app (local server + UI) and open it in the browser."""
    import threading
    import webbrowser

    import uvicorn

    from .web.server import create_app

    try:
        proj = find_project(project_path) if project_path else current_project()
    except ProjectNotFound:
        proj = None
    url = f"http://127.0.0.1:{port}/" + (f"p/{proj.id}" if proj else "")
    console.print(f"[bold]dsd[/] app on [cyan]{url}[/]  (Ctrl-C to stop)")
    if not no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    parent = os.environ.get("DSD_PARENT_PID")
    if parent:  # launched by the desktop app: exit with it, even if it is force-quit or crashes
        import signal
        import time

        def watch_parent(pid: int) -> None:
            while os.getppid() == pid:
                time.sleep(1.0)
            os.kill(os.getpid(), signal.SIGTERM)  # graceful: uvicorn shutdown closes PTY sessions

        threading.Thread(target=watch_parent, args=(int(parent),), daemon=True).start()
    current = proj.root if proj and proj.is_worktree else None
    uvicorn.run(create_app(current=current), host="127.0.0.1", port=port, log_level="warning")


@app.command()
def mcp() -> None:
    """Run the dsd MCP server on stdio (Claude Code starts this; register it with `dsd setup`)."""
    from .mcp_server import main

    main()


@app.command()
def info() -> None:
    """Show the current project."""
    p = _project()
    console.print(f"[bold]{p.name}[/]  id={p.id}")
    console.print(f"  repo   {p.repo}" + (f"  [dim](scope {p.scope})[/]" if p.scope else ""))
    if p.is_worktree:
        console.print(f"  root   {p.root}  [dim](worktree)[/]")
    console.print(f"  data   {p.data_dir}")
    console.print(f"  docs   {p.docs_path}")
    console.print(f"  runs   {p.runs_path}")


# ---------------------------------------------------------------- plans & tasks

plan_app = typer.Typer(no_args_is_help=True, help="Plans: the central plan and sub-plans.")
task_app = typer.Typer(no_args_is_help=True, help="Tasks inside plans (ids like T-12).")
app.add_typer(plan_app, name="plan")
app.add_typer(task_app, name="task")

_STATUS_STYLE = {"todo": "white", "doing": "cyan", "done": "green", "blocked": "red", "dropped": "dim"}
_STATUS_ICON = {"todo": "○", "doing": "◐", "done": "●", "blocked": "✕", "dropped": "–"}


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PlanError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _task_row(t: Task, show_plan: bool = False) -> str:
    style = _STATUS_STYLE[t.status]
    pad = "  " * (t.indent // 2)
    extra = " ".join([f"[magenta]#{x}[/]" for x in t.tags] + [f"[blue]@{k}:{v}[/]" for k, v in t.attrs.items()])
    where = f" [dim]({t.plan})[/]" if show_plan else ""
    return f"{pad}[{style}]{_STATUS_ICON[t.status]} {t.id or '—':>5}[/] {t.title} {extra}{where}".rstrip()


def _emit_json(data) -> None:
    import json as _json

    console.print_json(_json.dumps(data))


@plan_app.command("ls")
def plan_ls(json: bool = typer.Option(False, "--json")) -> None:
    """List plans with task counts."""
    p = _project()
    rows = []
    for pl in plans.load_plans(p):
        c = pl.counts()
        rows.append({"slug": pl.slug, "title": pl.title, "status": pl.meta.get("status", "active"), **c})
    if json:
        return _emit_json(rows)
    for r in rows:
        star = "★" if r["slug"] == plans.MAIN else " "
        console.print(
            f"{star} [bold]{r['slug']:<20}[/] {r['title']:<40} "
            f"[cyan]{r['doing']} doing[/]  {r['todo']} todo  [red]{r['blocked']} blocked[/]  [green]{r['done']} done[/]"
        )


@plan_app.command("show")
def plan_show(slug: str = typer.Argument(plans.MAIN), all: bool = typer.Option(False, "--all", "-a", help="Include done/dropped.")) -> None:
    """Show a plan's tasks (default: the central plan)."""
    p = _project()
    pl = _guard(plans.load_plan, p, slug)
    console.print(f"[bold]{pl.title}[/]  [dim]{pl.path}[/]")
    for t in pl.tasks:
        if all or t.status in plans.OPEN_STATUSES:
            console.print(_task_row(t))


@plan_app.command("new")
def plan_new(slug: str, title: str = typer.Option(None, "--title", "-t"), parent: str = typer.Option(plans.MAIN, "--parent")) -> None:
    """Create a sub-plan and link it from its parent plan."""
    p = _project()
    pl = _guard(plans.new_plan, p, slug, title, parent)
    console.print(f"[green]created[/] {pl.path}  (linked from {parent}.md)")


@plan_app.command("fmt")
def plan_fmt() -> None:
    """Give an id to every task that lacks one."""
    p = _project()
    for t in plans.fmt_ids(p):
        console.print(f"[green]{t.id}[/] {t.title} [dim]({t.plan})[/]")


@plan_app.command("check")
def plan_check() -> None:
    """Report duplicate or missing ids and unlinked sub-plans."""
    problems = plans.check(_project())
    for msg in problems:
        console.print(f"[yellow]•[/] {msg}")
    if problems:
        raise typer.Exit(1)
    console.print("[green]plans OK[/]")


@task_app.command("ls")
def task_ls(
    status: list[str] = typer.Option(None, "--status", "-s", help="todo/doing/done/blocked/dropped (repeatable). Default: open."),
    plan: str = typer.Option(None, "--plan", "-p"),
    tag: str = typer.Option(None, "--tag"),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """List tasks across all plans (default: open tasks)."""
    p = _project()
    wanted = set(status or plans.OPEN_STATUSES)
    tasks = [
        t for t in plans.all_tasks(p)
        if t.status in wanted and (plan is None or t.plan == plan) and (tag is None or tag.lstrip("#") in t.tags)
    ]
    if json:
        return _emit_json([t.to_dict() for t in tasks])
    for t in tasks:
        console.print(_task_row(t, show_plan=True))


@task_app.command("show")
def task_show(task_id: str, json: bool = typer.Option(False, "--json")) -> None:
    """Show one task with its notes."""
    p = _project()
    pl, t = _guard(plans.find_task, p, task_id)
    if json:
        return _emit_json(t.to_dict())
    console.print(_task_row(t))
    console.print(f"  [dim]plan {pl.slug} line {t.line + 1}{'  parent ' + t.parent if t.parent else ''}[/]")
    for n in t.notes:
        console.print(f"  {n}")


@task_app.command("add")
def task_add(
    title: str,
    plan: str = typer.Option(plans.MAIN, "--plan", "-p"),
    tag: list[str] = typer.Option(None, "--tag", help="Repeatable."),
    attr: list[str] = typer.Option(None, "--attr", help="key=value, repeatable."),
    parent: str = typer.Option(None, "--parent", help="Nest under this task id."),
    section: str = typer.Option("Tasks", "--section"),
) -> None:
    """Add a task (to the central plan's Tasks section by default)."""
    p = _project()
    attrs = {}
    for a in attr or []:
        k, _, v = a.partition("=")
        attrs[k.strip()] = v.strip()
    t = _guard(plans.add_task, p, title, plan, tag, attrs, parent, section)
    console.print(f"[green]added[/] {_task_row(t, show_plan=True)}")


def _transition(task_id: str, status: str, note: str | None) -> None:
    p = _project()
    pl, t = _guard(plans.find_task, p, task_id)
    plans.set_status(pl, t, status)
    if note:
        plans.append_note(pl, t, note)
    pl.save()
    console.print(_task_row(t, show_plan=True))


_NOTE = typer.Option(None, "--note", "-m", help="Append a note line under the task.")


@task_app.command("start")
def task_start(task_id: str, note: str = _NOTE) -> None:
    """Mark a task as doing."""
    _transition(task_id, "doing", note)


@task_app.command("done")
def task_done(task_id: str, note: str = _NOTE) -> None:
    """Mark a task as done."""
    _transition(task_id, "done", note)


@task_app.command("block")
def task_block(task_id: str, note: str = _NOTE) -> None:
    """Mark a task as blocked."""
    _transition(task_id, "blocked", note)


@task_app.command("drop")
def task_drop(task_id: str, note: str = _NOTE) -> None:
    """Mark a task as dropped."""
    _transition(task_id, "dropped", note)


@task_app.command("reopen")
def task_reopen(task_id: str, note: str = _NOTE) -> None:
    """Mark a task as todo again."""
    _transition(task_id, "todo", note)


@task_app.command("rm")
def task_rm(task_id: str, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Delete a task, with its notes and subtasks (prefer `dsd task drop` to keep the history)."""
    p = _project()
    pl, t = _guard(plans.find_task, p, task_id)
    if not yes:
        console.print(f"Would delete {_task_row(t, show_plan=True)} with its notes and subtasks. Re-run with --yes.")
        raise typer.Exit(1)
    removed = _guard(plans.remove_task, p, t.id)
    console.print(f"[green]deleted[/] {', '.join(removed)}")


@task_app.command("note")
def task_note(task_id: str, note: str) -> None:
    """Append a note under a task."""
    p = _project()
    pl, t = _guard(plans.find_task, p, task_id)
    plans.append_note(pl, t, note)
    pl.save()
    console.print(f"[green]noted[/] {t.id}")


@task_app.command("log")
def task_log(task_id: str) -> None:
    """Show commits carrying a `Task: T-12` trailer."""
    import subprocess

    p = _project()
    tid = _guard(plans.normalize_id, task_id)
    out = subprocess.run(
        ["git", "log", "--format=%h %ad %s", "--date=short", "-E", f"--grep=^Task:.*{tid}([^0-9]|$)"],
        cwd=p.root, capture_output=True, text=True,
    )
    console.print(out.stdout.rstrip() or f"[dim]no commits with 'Task: {tid}'[/]")


# ---------------------------------------------------------------- runs, benchmarks, exec

runs_app = typer.Typer(no_args_is_help=True, help="Experiment runs.")
bench_app = typer.Typer(no_args_is_help=True, help="Benchmarks (named groups of runs) and leaderboards.")
app.add_typer(runs_app, name="runs")
app.add_typer(bench_app, name="bench")

_RUN_STYLE = {"running": "cyan", "finished": "green", "failed": "red", "killed": "yellow",
              "crashed": "red", "queued": "blue"}


def short(rid: str) -> str:
    return rid[-8:].lower()


def _fmt_num(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if v != 0 and (abs(v) >= 1e5 or abs(v) < 1e-3):
            return f"{v:.3e}"
        return f"{v:.4g}"
    return str(v)


def _index():
    from .tracking.index import Index

    p = _project()
    idx = Index(p)
    idx.sync()
    return p, idx


def _resolve(idx, ref: str) -> str:
    try:
        return idx.resolve_id(ref)
    except KeyError as e:
        err.print(f"[red]{e.args[0]}[/red]")
        raise typer.Exit(1)


@runs_app.command("ls")
def runs_ls(
    benchmark: str = typer.Option(None, "--benchmark", "-b"),
    task: str = typer.Option(None, "--task", "-t"),
    status: str = typer.Option(None, "--status", "-s"),
    tag: str = typer.Option(None, "--tag"),
    where: list[str] = typer.Option(None, "--where", "-w", help="e.g. 'metrics.auc>=0.8' (repeatable)"),
    sort: str = typer.Option(None, "--sort", help="e.g. -metrics.auc"),
    metric: list[str] = typer.Option(None, "--metric", "-m", help="Metric columns to show."),
    limit: int = typer.Option(30, "--limit", "-n"),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """List runs (newest first)."""
    from rich.table import Table

    from .tracking.query import QueryError, list_runs

    p, idx = _index()
    if task:
        task = plans.normalize_id(task)
    try:
        rows = list_runs(idx, benchmark=benchmark, task=task, status=status, tag=tag, where=where, sort=sort, limit=limit)
    except QueryError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if json:
        return _emit_json(rows)
    keys = metric or sorted({k for r in rows for k in r["metrics"]})[:5]
    t = Table(box=None, header_style="bold dim")
    for col in ("id", "name", "status", "bench", "task", "created", *keys, "art"):
        t.add_column(col, justify="right" if col in keys or col == "art" else "left")
    for r in rows:
        st = r["status"]
        t.add_row(
            short(r["id"]), r["name"] or "", f"[{_RUN_STYLE.get(st, 'white')}]{st}[/]", r["benchmark"] or "",
            r["task"] or "", (r["created_at"] or "")[:16].replace("T", " "),
            *[_fmt_num(r["metrics"].get(k)) for k in keys], str(r["artifacts"] or ""),
        )
    console.print(t)


@runs_app.command("show")
def runs_show(ref: str, json: bool = typer.Option(False, "--json")) -> None:
    """Show a run: params, metrics, datasets, artifacts, git."""
    p, idx = _index()
    d = idx.run_detail(_resolve(idx, ref))
    if json:
        return _emit_json(d)
    st = d["status"]
    console.print(f"[bold]{d['name']}[/]  {d['id']}  [{_RUN_STYLE.get(st, 'white')}]{st}[/]")
    for k in ("benchmark", "task", "created_at", "ended_at", "error"):
        if d.get(k):
            console.print(f"  {k:<10} {d[k]}")
    if d.get("git"):
        g = d["git"]
        console.print(f"  git        {(g.get('sha') or '')[:10]} {g.get('branch') or ''}{' [yellow](dirty)[/]' if g.get('dirty') else ''}")
    if d.get("command"):
        console.print(f"  command    {' '.join(d['command'])}")
    if d["params"]:
        console.print("[bold]params[/]")
        for k, v in sorted(d["params"].items()):
            console.print(f"  {k:<28} {v}")
    if d["metric_stats"]:
        console.print("[bold]metrics[/]  [dim](last · min · max · n)[/]")
        for k, s in sorted(d["metric_stats"].items()):
            console.print(f"  {k:<28} {_fmt_num(s['last']):>10}  {_fmt_num(s['min']):>10}  {_fmt_num(s['max']):>10}  {s['n']}")
    if d["info"]:
        console.print("[bold]info[/]")
        for k, v in d["info"].items():
            console.print(f"  {k:<28} {v}")
    for ds in d["datasets"]:
        console.print(f"[bold]dataset[/] {ds}")
    if d["artifact_list"]:
        console.print("[bold]artifacts[/]")
        for a in d["artifact_list"]:
            console.print(f"  {a['path']:<40} {a['size']:>9}  {a.get('description') or ''}")


@runs_app.command("compare")
def runs_compare(refs: list[str], all: bool = typer.Option(False, "--all", "-a", help="Show identical params too.")) -> None:
    """Compare runs side by side (params that differ, metrics)."""
    from rich.table import Table

    from .tracking.query import compare

    p, idx = _index()
    c = compare(idx, [_resolve(idx, r) for r in refs])
    t = Table(box=None, header_style="bold")
    t.add_column("")
    for r in c["runs"]:
        t.add_column(f"{r['name']}\n[dim]{short(r['id'])}[/]", justify="right")
    t.add_row("[bold]metrics[/]", *[""] * len(c["runs"]))
    for m in c["metrics"]:
        vals = m["values"]
        nums = [v for v in vals if v is not None]
        best = max(nums) if nums else None
        t.add_row(f"  {m['key']}", *[f"[bold]{_fmt_num(v)}[/]" if v == best and len(nums) > 1 else _fmt_num(v) for v in vals])
    t.add_row("[bold]params[/]", *[""] * len(c["runs"]))
    for prm in c["params"]:
        if all or prm["differs"]:
            t.add_row(f"  {prm['key']}", *[str(v) for v in prm["values"]])
    console.print(t)


def _kv(items: list[str] | None, what: str) -> dict[str, str]:
    out = {}
    for item in items or []:
        k, sep, v = item.partition("=")
        if not sep or not k.strip():
            err.print(f"[red]{what} must look like key=value, got {item!r}[/red]")
            raise typer.Exit(2)
        out[k.strip()] = v.strip()
    return out


@runs_app.command("add")
def runs_add(
    name: str = typer.Argument(..., help="Run name, e.g. 'solver-v2 full estate'."),
    benchmark: str = typer.Option(None, "--benchmark", "-b"),
    task: str = typer.Option(None, "--task", "-t"),
    metric: list[str] = typer.Option(None, "--metric", "-m", help="key=value (repeatable)."),
    metrics_json: Path = typer.Option(None, "--metrics-json", help="JSON file of metrics (nested keys are flattened)."),
    param: list[str] = typer.Option(None, "--param", "-p", help="key=value (repeatable)."),
    params: Path = typer.Option(None, "--params", help="YAML/JSON config file recorded as params."),
    link: list[str] = typer.Option(None, "--link", "-l", help="label=URL, e.g. results=s3://bucket/run-7/ (repeatable)."),
    artifact: list[Path] = typer.Option(None, "--artifact", "-a", help="File or folder to copy into the run (repeatable)."),
    note: str = typer.Option(None, "--note", help="Free-text note shown with the run."),
    tag: list[str] = typer.Option(None, "--tag"),
    at: str = typer.Option(None, "--at", help="When the run happened (ISO date/time). Default: now."),
    commit: str = typer.Option(None, "--commit", help="Commit the run was made from. Default: the current checkout."),
) -> None:
    """Record a run that already happened (results from an HTML dump, a notebook, a remote job...)."""
    import json as _json

    from .tracking.execute import load_params_file
    from .tracking.query import _coerce
    from .tracking.record import RecordError, record_run

    p = _project()
    values: dict = _json.loads(metrics_json.read_text()) if metrics_json else {}
    values.update(_kv(metric, "--metric"))
    prm: dict = load_params_file(params) if params else {}
    prm.update({k: _coerce(v) for k, v in _kv(param, "--param").items()})
    try:
        bundle = record_run(p, name, benchmark=benchmark, task=plans.normalize_id(task) if task else None,
                            metrics=values, params=prm, links=_kv(link, "--link"), artifacts=artifact,
                            notes=note, tags=tag, created_at=at, commit=commit)
    except RecordError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]recorded[/] run [bold]{short(bundle.id)}[/] {name}"
                  + (f" on {benchmark}" if benchmark else "") + f"  [dim](dsd runs show {short(bundle.id)})[/]")


@runs_app.command("rm")
def runs_rm(refs: list[str], yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Delete runs (their bundles)."""
    import shutil

    p, idx = _index()
    ids = [_resolve(idx, r) for r in refs]
    if not yes:
        console.print(f"Would delete {len(ids)} run(s): {', '.join(short(i) for i in ids)}. Re-run with --yes.")
        raise typer.Exit(1)
    for rid in ids:
        shutil.rmtree(p.runs_path / rid, ignore_errors=True)
    idx.sync()
    console.print(f"[green]deleted[/] {len(ids)} run(s)")


@runs_app.command("reindex")
def runs_reindex() -> None:
    """Rebuild the SQLite index from run bundles."""
    p, idx = _index()
    stats = idx.rebuild()
    console.print(f"indexed {stats['added']} run(s)")


@app.command("open")
def open_(ref: str = typer.Argument(..., help="run id, or run-id/artifact-path")) -> None:
    """Open a run's HTML artifact (or its folder) with the system viewer."""
    import subprocess

    p, idx = _index()
    run_ref, _, art = ref.partition("/")
    d = idx.run_detail(_resolve(idx, run_ref))
    bundle = Path(d["bundle_path"])
    if art:
        target = bundle / "artifacts" / art
    else:
        htmls = [a["path"] for a in d["artifact_list"] if a["path"].endswith(".html")]
        target = bundle / "artifacts" / htmls[0] if htmls else bundle
    subprocess.run(["open", str(target)])


@bench_app.command("ls")
def bench_ls() -> None:
    """List benchmarks."""
    from .tracking.query import load_bench_specs

    p, idx = _index()
    specs = load_bench_specs(p)
    names = {b["name"]: b for b in idx.benchmarks()}
    for name in sorted(set(names) | set(specs)):
        b, s = names.get(name, {}), specs.get(name, {})
        rank = f"{s['primary']} ({s.get('direction', 'max')})" if s.get("primary") else "[dim]no primary metric[/]"
        console.print(f"[bold]{name:<24}[/] {b.get('runs', 0):>4} runs   {rank}")


@bench_app.command("set")
def bench_set(
    name: str,
    primary: str = typer.Option(None, "--primary", "-p", help="Primary metric used for ranking."),
    direction: str = typer.Option(None, "--direction", "-d", help="max or min"),
    description: str = typer.Option(None, "--description"),
) -> None:
    """Configure a benchmark's ranking (stored in the project's benchmarks.toml)."""
    from .tracking.query import QueryError, set_bench_spec

    p = _project()
    try:
        spec = set_bench_spec(p, name, primary, direction, description)
    except QueryError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{name}[/] {spec}")


@bench_app.command("board")
def bench_board(
    name: str,
    group_by: str = typer.Option(None, "--group-by", "-g", help="e.g. params.model or name"),
    where: list[str] = typer.Option(None, "--where", "-w"),
    all_status: bool = typer.Option(False, "--all-status", help="Include unfinished runs."),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Leaderboard for a benchmark (mean ± std per group when grouped)."""
    from rich.table import Table

    from .tracking.query import leaderboard

    p, idx = _index()
    b = leaderboard(idx, p, name, group_by=group_by, status=None if all_status else "finished", where=where)
    if json:
        return _emit_json(b)
    primary = b["spec"].get("primary")
    keys = b["metrics"][:8]
    t = Table(box=None, header_style="bold", title=f"{name}" + (f" · ranked by {primary} ({b['spec'].get('direction', 'max')})" if primary else ""))
    t.add_column("#", justify="right")
    t.add_column(group_by if b["grouped"] else "run")
    if b["grouped"]:
        t.add_column("n", justify="right")
    for k in keys:
        t.add_column(k, justify="right", style="bold" if k == primary else None)
    for row in b["rows"]:
        if b["grouped"]:
            cells = []
            for k in keys:
                s = row["stats"][k]
                cells.append("—" if s["mean"] is None else f"{_fmt_num(s['mean'])} ± {_fmt_num(s['std'])}" if s["n"] > 1 else _fmt_num(s["mean"]))
            t.add_row(str(row.get("rank") or ""), row["group"], str(row["n"]), *cells)
        else:
            t.add_row(str(row["rank"] or ""), f"{row['run']['name']} [dim]{short(row['run']['id'])}[/]",
                      *[_fmt_num(row["metrics"].get(k)) for k in keys])
    console.print(t)


backup_app = typer.Typer(help="Back up docs (and optionally runs). Run with no subcommand to snapshot now.",
                         invoke_without_command=True)
app.add_typer(backup_app, name="backup")


@backup_app.callback()
def backup_now(ctx: typer.Context, target: str = typer.Option(None, "--target")) -> None:
    """Snapshot to every configured target (or just --target)."""
    if ctx.invoked_subcommand:
        return
    from . import backup as bk

    p = _project()
    tgts = bk.targets(p)
    if not tgts:
        err.print("No backup target configured. Add one:  dsd backup add-local ~/path/to/backups")
        raise typer.Exit(1)
    for t, cfg in zip(tgts, p.backup):
        if target and t.name != target:
            continue
        res = t.push(p, bk.include_paths(p, cfg))
        console.print(f"[green]{t.name}[/] snapshot {res.snapshot}: {res.files} files "
                      f"({res.copied} copied, {res.linked} unchanged) → {res.location}")


@backup_app.command("add-local")
def backup_add_local(path: str, name: str = typer.Option("local", "--name"),
                     include_runs: bool = typer.Option(False, "--include-runs")) -> None:
    """Add a local snapshot target (e.g. a folder in iCloud Drive or Dropbox)."""
    from . import backup as bk

    entry = bk.add_local_target(_project(), path, name, include_runs)
    console.print(f"[green]added[/] backup target {entry}")


@backup_app.command("ls")
def backup_ls() -> None:
    """List snapshots per target."""
    from . import backup as bk

    p = _project()
    for t in bk.targets(p):
        snaps = t.list_snapshots(p)
        console.print(f"[bold]{t.name}[/] ({len(snaps)} snapshots)")
        for s in snaps:
            console.print(f"  {s.name}  {s.files} files")


@backup_app.command("restore")
def backup_restore(snapshot: str, to: Path = typer.Option(..., "--to", help="Destination folder (never restores in place)."),
                   target: str = typer.Option(None, "--target")) -> None:
    """Restore a snapshot into a folder."""
    from . import backup as bk

    p = _project()
    for t in bk.targets(p):
        if target and t.name != target:
            continue
        try:
            n = t.restore(p, snapshot, to)
        except FileNotFoundError:
            continue
        console.print(f"[green]restored[/] {n} files to {to}")
        return
    err.print(f"[red]snapshot {snapshot} not found[/red]")
    raise typer.Exit(1)


todo_app = typer.Typer(no_args_is_help=True, help="Personal to-dos on your dsd Home (cross-project).")
app.add_typer(todo_app, name="todo")


def _print_todo(t: dict) -> None:
    from datetime import date as _date

    mark = {"todo": "○", "doing": "◐", "done": "●", "blocked": "✕", "dropped": "–"}[t["status"]]
    due = t.get("due")
    style = "red" if due and due < _date.today().isoformat() and t["status"] not in ("done", "dropped") else "cyan"
    due_s = f" [{style}]{due}[/]" if due else ""
    proj = f" [magenta]#{t['project']}[/]" if t.get("project") else ""
    src = f" [dim]({t['project']} {t['id']})[/]" if t.get("source") == "project" else ""
    console.print(f"{mark} [dim]{t['id']:>5}[/] {t['title']}{due_s}{proj if not src else ''}{src}")


@todo_app.command("add")
def todo_add(text: list[str] = typer.Argument(..., help='e.g. Send David the numbers tomorrow #churn-model')) -> None:
    """Add a to-do; dates ('tomorrow', 'fri', '11/14') and #project in the text are understood."""
    from . import home

    _print_todo(home.add_todo(" ".join(text)))


@todo_app.command("ls")
def todo_ls(json: bool = typer.Option(False, "--json")) -> None:
    """List open to-dos (and ones completed today)."""
    from . import home

    ts = home.list_todos()
    if json:
        return _emit_json(ts)
    for t in sorted(ts, key=lambda t: (t["status"] in ("done", "dropped"), t["due"] or "9999")):
        _print_todo(t)


@todo_app.command("done")
def todo_done(task_id: str) -> None:
    """Mark a to-do done."""
    from . import home

    _print_todo(_guard(home.update_todo, plans.normalize_id(task_id), "done"))


@todo_app.command("move")
def todo_move(task_id: str, when: list[str] = typer.Argument(..., help="today, tomorrow, fri, 2026-11-20, none")) -> None:
    """Reschedule a to-do."""
    from . import home

    w = " ".join(when)
    if w.strip().lower() in ("none", "someday", "-"):
        due = None
    else:
        _, d = home.parse_due(w)
        if d is None:
            err.print(f"[red]Couldn't understand '{w}' as a date[/red]")
            raise typer.Exit(1)
        due = d.isoformat()
    _print_todo(_guard(home.update_todo, plans.normalize_id(task_id), None, due))


@app.command()
def today() -> None:
    """Your day across projects: overdue, today, and what needs attention."""
    from datetime import date as _date, timedelta as _td

    from . import home

    d = home.dashboard()
    console.print(f"[bold]{_date.today():%A %d %B}[/]  [dim]{d['summary']}[/]")
    t0, t1 = d["today"], (_date.today() + _td(days=1)).isoformat()
    groups = [("Overdue", lambda t: t["due"] and t["due"] < t0), ("Today", lambda t: t["due"] == t0),
              ("Tomorrow", lambda t: t["due"] == t1)]
    open_items = [t for t in d["agenda"] if t["status"] in plans.OPEN_STATUSES]
    for label, pred in groups:
        items = [t for t in open_items if pred(t)]
        if items:
            console.print(f"\n[bold]{label}[/]")
            for t in items:
                _print_todo(t)
    if d["attention"]:
        console.print("\n[bold]Needs you[/]")
        for a in d["attention"]:
            console.print(f"  [yellow]•[/] [magenta]{a['project']}[/] {a['text']}")


wt_app = typer.Typer(no_args_is_help=True, help="Git worktrees for parallel agent sessions (branches dsd/<name>).")
app.add_typer(wt_app, name="wt")


def _wt_guard(fn, *a, **kw):
    from .worktrees import WorktreeError

    try:
        return fn(*a, **kw)
    except WorktreeError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@wt_app.command("ls")
def wt_ls(json: bool = typer.Option(False, "--json"),
          all: bool = typer.Option(False, "--all", "-a", help="Also list other worktrees of the repo you could adopt.")) -> None:
    """List the main checkout and dsd's worktrees (created, adopted, or the one you're in) with status."""
    from . import worktrees as wt

    p = _project()
    rows = _wt_guard(wt.list_worktrees, p, include=[Path.cwd()])
    others = _wt_guard(wt.candidates, p) if all else []
    others = [c for c in others if c["path"] not in {r["path"] for r in rows}]
    if json:
        return _emit_json(rows + [{**c, "origin": None} for c in others])
    for w in rows:
        ab = "" if w["is_main"] or w.get("ahead") is None else f"  [green]↑{w['ahead']}[/] [yellow]↓{w['behind']}[/] vs {w['base']}"
        dirty = f"  [yellow]{w['dirty']} changed[/]" if w.get("dirty") else ""
        task = f"  [dim]{w['task']}[/]" if w.get("task") else ""
        console.print(f"{'★' if w['is_main'] else ' '} [bold]{w['name']:<24}[/] {w['branch'] or '(detached)':<28}{ab}{dirty}{task}")
        if not w["is_main"]:
            origin = "" if w["origin"] == "dsd" else f"  [magenta]{w['origin']}[/]"
            console.print(f"    [dim]{w['path']}[/]{origin}")
    if others:
        console.print("\n[bold]Not listed[/] [dim](adopt with: dsd wt adopt <path>)[/]")
        for c in others:
            console.print(f"  {c['branch'] or '(detached)':<36} [dim]{c['path']}[/]")


@wt_app.command("adopt")
def wt_adopt(path: Path = typer.Argument(..., help="An existing worktree of this repo (e.g. one made by Pane)."),
             task: str = typer.Option(None, "--task", "-t", help="Link to a plan task, e.g. T-12.")) -> None:
    """Add an existing worktree to dsd's list. dsd never deletes it unless you remove it explicitly."""
    from . import worktrees as wt

    w = _wt_guard(wt.adopt_worktree, _project(), str(path), plans.normalize_id(task) if task else None)
    console.print(f"[green]adopted[/] {w['name']} ({w['branch'] or 'detached'})")


@wt_app.command("move")
def wt_move(name: str, to: str = typer.Option(..., "--to", help="Another project on this repo (name or id).")) -> None:
    """Hand a worktree to another project on the same repo; dsd in that worktree then resolves to it."""
    from . import worktrees as wt

    p = _project()
    w = _wt_guard(wt.move_worktree, p, name, _repo_project(p, to))
    console.print(f"[green]moved[/] {w['name']} to {to}")


@wt_app.command("hide")
def wt_hide(name: str) -> None:
    """Stop listing a worktree; its directory and branch are left alone."""
    from . import worktrees as wt

    console.print(f"[green]hidden[/] {_wt_guard(wt.hide_worktree, _project(), name)['hidden']}")


@wt_app.command("new")
def wt_new(
    name: str = typer.Argument(None, help="Name (default: from --task, else random)."),
    base: str = typer.Option(None, "--base", "-b", help="Base branch (default: current branch)."),
    task: str = typer.Option(None, "--task", "-t", help="Link to a plan task, e.g. T-12."),
) -> None:
    """Create a worktree + branch dsd/<name>; prints its path (cd "$(dsd wt new x)")."""
    from . import worktrees as wt

    p = _project()
    title = None
    if task:
        task = plans.normalize_id(task)
        try:
            title = plans.find_task(p, task)[1].title
        except PlanError:
            pass
    w = _wt_guard(wt.create_worktree, p, name, base, task, title)
    err.print(f"[green]created[/] {w['name']} on {w['branch']} (from {w['base']})"
              + (f", copied {', '.join(w['copied'])}" if w.get("copied") else ""))
    print(w["path"])


@wt_app.command("path")
def wt_path(name: str) -> None:
    """Print a worktree's path (cd "$(dsd wt path x)")."""
    from . import worktrees as wt

    print(_wt_guard(wt.get_worktree, _project(), name)["path"])


@wt_app.command("rm")
def wt_rm(name: str, force: bool = typer.Option(False, "--force", "-f", help="Discard uncommitted changes."),
          delete_branch: bool = typer.Option(False, "--delete-branch", "-d")) -> None:
    """Remove a worktree (refuses if it has uncommitted changes, unless --force)."""
    from . import worktrees as wt

    r = _wt_guard(wt.remove_worktree, _project(), name, force, delete_branch)
    console.print(f"[green]removed[/] {r['removed']}" + (" and its branch" if r["branch_deleted"] else ""))


@wt_app.command("merge")
def wt_merge(name: str, squash: bool = typer.Option(False, "--squash"), message: str = typer.Option(None, "-m")) -> None:
    """Merge a worktree's branch into its base in the main checkout (aborts cleanly on conflict)."""
    from . import worktrees as wt

    r = _wt_guard(wt.merge_worktree, _project(), name, "squash" if squash else "merge", message)
    console.print(f"[green]merged[/] {r['merged']} into {r['into']} ({r['commit']})")


@app.command("exec", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def exec_(
    ctx: typer.Context,
    name: str = typer.Option(None, "--name", "-n"),
    benchmark: str = typer.Option(None, "--benchmark", "-b"),
    task: str = typer.Option(None, "--task", "-t"),
    tag: list[str] = typer.Option(None, "--tag"),
    params: Path = typer.Option(None, "--params", help="YAML/JSON config file recorded as params."),
    param: list[str] = typer.Option(None, "--param", "-p", help="key=value (repeatable)."),
    dataset: list[str] = typer.Option(None, "--dataset", help="id, URL, or path to a config.yml (repeatable)."),
) -> None:
    """Run a command as a tracked experiment:  dsd exec -b churn-v1 -- python train.py --config x.yaml"""
    from .tracking.capture import dataset as make_ds
    from .tracking.execute import exec_command, load_params_file
    from .tracking.query import _coerce

    cmd = list(ctx.args)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        err.print("[red]usage: dsd exec [options] -- <command> [args...][/red]")
        raise typer.Exit(2)
    p = _project()
    prm: dict = load_params_file(params) if params else {}
    for kv in param or []:
        k, _, v = kv.partition("=")
        prm[k.strip()] = _coerce(v.strip())
    dss = []
    for ds in dataset or []:
        if Path(ds).suffix in (".yml", ".yaml", ".json", ".toml") and Path(ds).exists():
            dss.append(make_ds(config=ds))
        elif "://" in ds or ds.startswith("git@"):
            dss.append(make_ds(uri=ds))
        else:
            dss.append(make_ds(id=ds))
    if params:
        dss_cfg = {"params_file": str(params)}
    else:
        dss_cfg = {}
    if task:
        task = plans.normalize_id(task)
    bundle, code = exec_command(p, cmd, name=name, benchmark=benchmark, task=task, tags=tag, params=prm, datasets=dss)
    if dss_cfg:
        bundle.update_meta(info={**bundle.read_meta().get("info", {}), **dss_cfg})
    meta = bundle.read_meta()
    st = meta["status"]
    err.print(f"[dim]dsd:[/] run [bold]{short(bundle.id)}[/] {meta['name']} → [{_RUN_STYLE.get(st, 'white')}]{st}[/]"
              f"  [dim](dsd runs show {short(bundle.id)})[/]")
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
