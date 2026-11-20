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


def test_cli_default_and_wt_move(tmp_path, monkeypatch):
    import subprocess

    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    runner = CliRunner()
    assert runner.invoke(app, ["init", str(tmp_path), "--name", "mono"]).exit_code == 0
    assert runner.invoke(app, ["init", str(tmp_path), "--name", "sof"]).exit_code == 0
    monkeypatch.chdir(tmp_path)
    assert "★ mono" in runner.invoke(app, ["default"]).output
    wt_path = runner.invoke(app, ["wt", "new", "feature"]).stdout.strip().splitlines()[-1]
    r = runner.invoke(app, ["wt", "move", "feature", "--to", "sof"])
    assert r.exit_code == 0, r.output
    monkeypatch.chdir(wt_path)
    assert "sof" in runner.invoke(app, ["info"]).output.splitlines()[0]
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["default", "sof"]).exit_code == 0
    assert "sof" in runner.invoke(app, ["info"]).output.splitlines()[0]
    assert runner.invoke(app, ["default", "nope"]).exit_code == 1
