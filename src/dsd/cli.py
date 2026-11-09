"""`dsd` command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from .init import init_project
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


if __name__ == "__main__":
    app()
