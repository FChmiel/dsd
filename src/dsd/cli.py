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
    report = init_project(path, name=name)
    for action, rel in report.actions:
        if action != "unchanged":
            console.print(f"  [{_STYLE[action]}]{action:9}[/] {rel}")
    p = report.project
    if report.changed:
        console.print(f"[bold]dsd project '{p.name}'[/] ready at {p.root}  (id {p.id})")
    else:
        console.print(f"dsd project '{p.name}' already up to date.")


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


if __name__ == "__main__":
    app()
