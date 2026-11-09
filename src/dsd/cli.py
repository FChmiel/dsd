"""`dsd` command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from . import plans
from .init import init_project, refresh_claude_md
from .plans import PlanError, Task
from .project import ProjectNotFound, find_project

app = typer.Typer(no_args_is_help=True, add_completion=False, help="dsd: plans, docs and experiment tracking.")
console = Console()
err = Console(stderr=True)

_STYLE = {"created": "green", "updated": "yellow", "unchanged": "dim"}


def _project():
    try:
        return find_project()
    except ProjectNotFound as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Print the dsd version."""
    console.print(__version__)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Project root (default: current directory)."),
    name: str = typer.Option(None, "--name", "-n", help="Project name (default: directory name)."),
) -> None:
    """Set up a dsd project here. Safe to re-run: it only adds what's missing."""
    from . import registry

    report = init_project(path, name=name)
    registry.register(report.project.root)
    for action, rel in report.actions:
        if action != "unchanged":
            console.print(f"  [{_STYLE[action]}]{action:9}[/] {rel}")
    p = report.project
    if report.changed:
        console.print(f"[bold]dsd project '{p.name}'[/] ready at {p.root}  (id {p.id})")
    else:
        console.print(f"dsd project '{p.name}' already up to date.")


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

    from .project import load_project
    from .web.server import create_app

    initial = []
    try:
        proj = load_project(project_path.resolve()) if project_path else find_project()
        initial.append(proj.root)
    except ProjectNotFound:
        proj = None
    url = f"http://127.0.0.1:{port}/" + (f"p/{proj.id}" if proj else "")
    console.print(f"[bold]dsd[/] app on [cyan]{url}[/]  (Ctrl-C to stop)")
    if not no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(initial), host="127.0.0.1", port=port, log_level="warning")


@app.command()
def mcp() -> None:
    """Run the dsd MCP server on stdio (Claude Code starts this via .mcp.json)."""
    from .mcp_server import main

    main()


@app.command()
def info() -> None:
    """Show the current project."""
    p = _project()
    console.print(f"[bold]{p.name}[/]  id={p.id}")
    console.print(f"  root   {p.root}")
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


def _sync_claude(p) -> None:
    active = [(t.id, t.title) for t in plans.all_tasks(p) if t.status == "doing" and t.id]
    refresh_claude_md(p, active)


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
    console.print(f"[bold]{pl.title}[/]  [dim]{pl.path.relative_to(p.root)}[/]")
    for t in pl.tasks:
        if all or t.status in plans.OPEN_STATUSES:
            console.print(_task_row(t))


@plan_app.command("new")
def plan_new(slug: str, title: str = typer.Option(None, "--title", "-t"), parent: str = typer.Option(plans.MAIN, "--parent")) -> None:
    """Create a sub-plan and link it from its parent plan."""
    p = _project()
    pl = _guard(plans.new_plan, p, slug, title, parent)
    console.print(f"[green]created[/] {pl.path.relative_to(p.root)}  (linked from {parent}.md)")


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
    _sync_claude(p)
    console.print(_task_row(t, show_plan=True))


_NOTE = typer.Option(None, "--note", "-m", help="Append a note line under the task.")


@task_app.command("start")
def task_start(task_id: str, note: str = _NOTE) -> None:
    """Mark a task as doing (and show it as active in CLAUDE.md)."""
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
    """Configure a benchmark's ranking (stored in .dsd/benchmarks.toml)."""
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
def wt_ls(json: bool = typer.Option(False, "--json")) -> None:
    """List the main checkout and worktrees with branch, dirty files and ahead/behind."""
    from . import worktrees as wt

    rows = _wt_guard(wt.list_worktrees, _project())
    if json:
        return _emit_json(rows)
    for w in rows:
        ab = "" if w["is_main"] or w.get("ahead") is None else f"  [green]↑{w['ahead']}[/] [yellow]↓{w['behind']}[/] vs {w['base']}"
        dirty = f"  [yellow]{w['dirty']} changed[/]" if w.get("dirty") else ""
        task = f"  [dim]{w['task']}[/]" if w.get("task") else ""
        console.print(f"{'★' if w['is_main'] else ' '} [bold]{w['name']:<24}[/] {w['branch'] or '(detached)':<28}{ab}{dirty}{task}")
        if not w["is_main"]:
            console.print(f"    [dim]{w['path']}[/]")


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
