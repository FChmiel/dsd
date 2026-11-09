import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dsd.cli import app
from dsd.ids import ulid
from dsd.init import CLAUDE_END, CLAUDE_START, init_project
from dsd.managed import read_block, upsert_block
from dsd.project import ProjectNotFound, find_project


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_init_creates_layout(tmp_path):
    report = init_project(tmp_path, name="churn")
    assert report.changed
    data = tomllib.loads((tmp_path / ".dsd/project.toml").read_text())
    assert data["name"] == "churn" and len(data["id"]) == 26
    for sub in ("plans", "decisions", "notes", "reports", "experiments"):
        assert (tmp_path / "docs" / sub).is_dir()
    assert (tmp_path / ".dsd/runs").is_dir()
    main = (tmp_path / "docs/plans/main.md").read_text()
    assert "churn: main plan" in main and "- [ ] T-1 " in main
    gi = (tmp_path / ".gitignore").read_text()
    assert ".dsd/runs/" in gi and ".dsd/index.db" in gi
    claude = (tmp_path / "CLAUDE.md").read_text()
    assert "docs/plans/main.md" in read_block(claude, CLAUDE_START, CLAUDE_END)


def test_init_is_idempotent(tmp_path):
    init_project(tmp_path, name="churn")
    before = snapshot(tmp_path)
    report = init_project(tmp_path, name="ignored-on-rerun")
    assert not report.changed
    assert snapshot(tmp_path) == before


def test_init_preserves_existing_files(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    (tmp_path / "CLAUDE.md").write_text("# My rules\n\nBe terse.\n")
    init_project(tmp_path)
    assert (tmp_path / ".gitignore").read_text().startswith("node_modules/\n")
    claude = (tmp_path / "CLAUDE.md").read_text()
    assert claude.startswith("# My rules\n\nBe terse.\n")
    assert CLAUDE_START in claude


def test_init_never_overwrites_user_plan(tmp_path):
    init_project(tmp_path)
    plan = tmp_path / "docs/plans/main.md"
    plan.write_text("# my own plan\n")
    init_project(tmp_path)
    assert plan.read_text() == "# my own plan\n"


def test_init_restores_deleted_main_plan(tmp_path):
    init_project(tmp_path)
    (tmp_path / "docs/plans/main.md").unlink()
    report = init_project(tmp_path)
    assert ("created", "docs/plans/main.md") in report.actions


def test_find_project_from_subdir(tmp_path):
    init_project(tmp_path, name="p")
    sub = tmp_path / "src/deep"
    sub.mkdir(parents=True)
    assert find_project(sub).name == "p"
    with pytest.raises(ProjectNotFound):
        find_project(tmp_path.parent / "elsewhere-does-not-exist-xyz")


def test_upsert_block_replaces_in_place():
    text = "a\n<!--s-->\nold\n<!--e-->\nb\n"
    assert upsert_block(text, "<!--s-->", "<!--e-->", "new") == "a\n<!--s-->\nnew\n<!--e-->\nb\n"


def test_ulid_sortable():
    a, b = ulid(1000), ulid(2000)
    assert len(a) == 26 and a < b


def test_cli_init_and_info(tmp_path, monkeypatch):
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(tmp_path), "--name", "demo"])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0 and "demo" in result.output
