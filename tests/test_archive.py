import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dsd import archive, worktrees
from dsd.init import init_project
from dsd.project import ProjectNotFound, all_projects, find_project
from dsd.web.server import create_app

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd, *args):
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "train.py").write_text("lr = 1\n")
    (root / ".gitignore").write_text(".env\n")
    (root / ".env").write_text("SECRET=1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def test_archive_hides_the_project_and_parks_its_worktrees(repo, tmp_path):
    mono = init_project(repo, name="mono").project
    work = init_project(repo, name="staff-on-floor").project
    w = worktrees.create_worktree(work, name="sof")
    Path(w["path"], "train.py").write_text("lr = 2\n")
    git(Path(w["path"]), "commit", "-qam", "work")
    ext = tmp_path / "external"
    git(repo, "worktree", "add", "-q", "-b", "theirs", str(ext))
    worktrees.adopt_worktree(work, str(ext))
    (work.docs_path / "notes" / "keep.md").write_text("kept\n")

    preview = archive.preview(work)
    assert [x["name"] for x in preview["remove"]] == ["sof"] and preview["blockers"] == []
    assert [x["name"] for x in preview["unlist"]] == ["external"]
    res = archive.archive_project(work)
    assert res["removed"] == ["sof"]

    assert not Path(w["path"]).exists() and ext.is_dir()
    assert "dsd/sof" in worktrees.branches(mono) and "theirs" in worktrees.branches(mono)
    assert [p.name for p in all_projects()] == ["mono"]
    assert [p.name for p in all_projects(include_archived=True)] == ["mono", "staff-on-floor"]
    assert find_project(repo).id == mono.id
    assert find_project(ext).id == mono.id
    assert (work.docs_path / "notes" / "keep.md").read_text() == "kept\n"


def test_uncommitted_work_blocks_archive_unless_forced(repo):
    work = init_project(repo, name="work").project
    w = worktrees.create_worktree(work, name="dirty")
    Path(w["path"], "scratch.py").write_text("x = 1\n")
    assert [b["name"] for b in archive.preview(work)["blockers"]] == ["dirty"]
    with pytest.raises(archive.ArchiveError, match="uncommitted"):
        archive.archive_project(work)
    assert Path(w["path"]).is_dir() and not all_projects(include_archived=True)[0].archived
    archive.archive_project(work, force=True)
    assert not Path(w["path"]).exists()


def test_restore_brings_back_the_project_and_its_worktrees(repo):
    work = init_project(repo, name="work").project
    w = worktrees.create_worktree(work, name="sof")
    Path(w["path"], "train.py").write_text("lr = 3\n")
    git(Path(w["path"]), "commit", "-qam", "work")
    archive.archive_project(work)
    with pytest.raises(ProjectNotFound, match="archived"):
        find_project(repo)
    with pytest.raises(ValueError, match="archived"):
        init_project(repo, name="work")

    res = archive.restore_project(work)
    assert res["restored"] == ["sof"]
    assert Path(w["path"], "train.py").read_text() == "lr = 3\n"
    assert Path(w["path"], ".env").read_text() == "SECRET=1\n"
    assert find_project(Path(w["path"])).id == work.id
    assert [x["name"] for x in worktrees.list_worktrees(work)] == ["main", "sof"]


def test_restore_skips_worktrees_whose_branch_is_gone(repo):
    work = init_project(repo, name="work").project
    worktrees.create_worktree(work, name="gone")
    archive.archive_project(work)
    git(repo, "branch", "-D", "dsd/gone")
    res = archive.restore_project(work)
    assert res["restored"] == [] and res["missing"] == ["gone"]
    assert [x["name"] for x in worktrees.list_worktrees(work)] == ["main"]


def test_archive_api_closes_sessions(repo):
    work = init_project(repo, name="work").project
    with TestClient(create_app()) as c:
        t = c.post(f"/api/p/{work.id}/terminals", json={"kind": "shell", "new_worktree": {"name": "s"}}).json()
        assert c.get(f"/api/p/{work.id}/archive").json()["remove"][0]["name"] == "s"
        assert c.post(f"/api/p/{work.id}/archive", json={}).status_code == 200
        assert c.get(f"/api/p/{work.id}/terminals").json() == []
        assert t["id"] not in [x["id"] for x in c.get(f"/api/p/{work.id}/terminals").json()]
        assert c.get("/api/projects").json() == []
        assert [p["name"] for p in c.get("/api/projects/archived").json()] == ["work"]
        assert c.get(f"/api/p/{work.id}/overview").status_code == 404
        r = c.post(f"/api/projects/{work.id}/restore").json()
        assert r["restored"] == ["s"]
        assert [p["name"] for p in c.get("/api/projects").json()] == ["work"]


def test_cli_archive_and_restore(repo, monkeypatch):
    from typer.testing import CliRunner

    from dsd.cli import app

    work = init_project(repo, name="work").project
    w = worktrees.create_worktree(work, name="sof")
    monkeypatch.chdir(repo)
    runner = CliRunner()
    r = runner.invoke(app, ["archive", "work"])
    assert r.exit_code == 1 and "remove worktree sof" in r.output and Path(w["path"]).is_dir()
    r = runner.invoke(app, ["archive", "work", "--yes"])
    assert r.exit_code == 0, r.output
    assert not Path(w["path"]).exists()
    assert "work" not in runner.invoke(app, ["projects"]).output
    assert "archived" in runner.invoke(app, ["projects", "-a"]).output
    assert "archived" in runner.invoke(app, ["info"]).output
    r = runner.invoke(app, ["restore", "work"])
    assert r.exit_code == 0 and "with sof" in r.output and Path(w["path"]).is_dir()
