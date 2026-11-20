from typer.testing import CliRunner

from dsd.cli import app
from dsd.ids import ulid
from dsd.init import init_project


def test_init_creates_layout(tmp_path):
    report = init_project(tmp_path, name="churn")
    assert report.changed
    p = report.project
    assert len(p.id) == 26
    for sub in ("plans", "decisions", "notes", "reports", "experiments"):
        assert (p.docs_path / sub).is_dir()
    main = p.main_plan_path.read_text()
    assert "churn: main plan" in main and "- [ ] T-1 " in main
    assert list(tmp_path.iterdir()) == []


def test_init_never_overwrites_user_plan(tmp_path):
    p = init_project(tmp_path).project
    p.main_plan_path.write_text("# my own plan\n")
    init_project(tmp_path)
    assert p.main_plan_path.read_text() == "# my own plan\n"


def test_init_restores_deleted_main_plan(tmp_path):
    p = init_project(tmp_path).project
    p.main_plan_path.unlink()
    report = init_project(tmp_path)
    assert ("created", "docs/plans/main.md") in report.actions


def test_ulid_sortable():
    a, b = ulid(1000), ulid(2000)
    assert len(a) == 26 and a < b


def test_cli_init_and_info(tmp_path, monkeypatch):
    runner = CliRunner()
    (tmp_path / "apps" / "x").mkdir(parents=True)
    result = runner.invoke(app, ["init", str(tmp_path), "--name", "demo"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["init", str(tmp_path), "--scope", "apps/x"])
    assert result.exit_code == 0 and "scope apps/x" in result.output, result.output
    assert runner.invoke(app, ["init", str(tmp_path), "--scope", "nope"]).exit_code == 1
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0 and "demo" in result.output
    monkeypatch.chdir(tmp_path / "apps" / "x")
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0 and "x" in result.output and "scope apps/x" in result.output


def test_project_root_env_overrides_cwd(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    init_project(tmp_path / "a", name="alpha")
    init_project(tmp_path / "b", name="beta")
    monkeypatch.chdir(tmp_path / "a")
    runner = CliRunner()
    assert "alpha" in runner.invoke(app, ["info"]).output
    monkeypatch.setenv("DSD_PROJECT_ROOT", str(tmp_path / "b"))
    assert "beta" in runner.invoke(app, ["info"]).output
