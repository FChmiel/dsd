import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dsd
from dsd import review, worktrees
from dsd.init import init_project
from dsd.project import load_project
from dsd.tracking.bundle import Bundle
from dsd.web.server import create_app

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd, *args):
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    init_project(root, name="wt-demo")
    (root / "train.py").write_text("lr = 0.1\nepochs = 10\n")
    (root / ".env").write_text("SECRET=1\n")  # untracked local file worktrees should get a copy of
    (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".env\n")
    # commit everything except .mcp.json, so bootstrap has something dsd-specific to copy
    git(root, "add", "-A")
    git(root, "reset", "-q", ".mcp.json")
    git(root, "commit", "-qm", "init")
    monkeypatch.delenv("DSD_RUN_DIR", raising=False)
    return load_project(root)


def test_create_list_and_bootstrap(repo):
    gi = repo.root / ".gitignore"
    gi.write_text(gi.read_text().replace(".dsd/worktrees.json\n", ""))  # simulate a project from before worktrees
    w = worktrees.create_worktree(repo, task="T-6", task_title="Add interaction features")
    assert w["name"] == "t-6-add-interaction-features" and w["branch"] == "dsd/t-6-add-interaction-features"
    assert w["base"] == "main" and w["task"] == "T-6"
    path = Path(w["path"])
    assert path.is_dir() and str(path).startswith(str(worktrees.base_dir(repo)))
    assert ".mcp.json" in w["copied"] and ".env" in w["copied"]
    assert (path / ".env").read_text() == "SECRET=1\n"
    assert ".dsd/worktrees.json" in gi.read_text()  # managed block refreshed
    # same name again gets a suffix
    w2 = worktrees.create_worktree(repo, name="t-6-add-interaction-features")
    assert w2["name"] == "t-6-add-interaction-features-2"
    names = [x["name"] for x in worktrees.list_worktrees(repo)]
    assert names[0] == "main" and set(names[1:]) == {w["name"], w2["name"]}


def test_worktree_project_shares_state(repo, monkeypatch):
    w = worktrees.create_worktree(repo, name="exp")
    wp = load_project(Path(w["path"]))
    assert wp.is_worktree and wp.main_root == repo.root
    assert wp.runs_path == repo.runs_path and wp.index_path == repo.index_path
    monkeypatch.setenv("DSD_PROJECT_ROOT", w["path"])
    with dsd.run("from-wt") as r:
        r.log(auc=0.9)
    assert r.dir.parent == repo.runs_path  # stored centrally
    meta = Bundle(r.dir).read_meta()
    assert meta["worktree"] == "exp" and meta["git"]["branch"] == "dsd/exp"


def test_changes_vs_base_and_merge(repo):
    w = worktrees.create_worktree(repo, name="lr")
    path = Path(w["path"])
    (path / "train.py").write_text("lr = 0.3\nepochs = 10\n")
    git(path, "commit", "-qam", "bump lr")
    (path / "notes.txt").write_text("new file\n")  # untracked
    (path / "train.py").write_text("lr = 0.3\nepochs = 20\n")  # uncommitted on top of the commit
    ch = review.working_changes(repo, path, base="main")
    by = {f["path"]: f for f in ch["files"]}
    assert by["train.py"]["additions"] == 2 and by["notes.txt"]["status"] == "added"
    st = [x for x in worktrees.list_worktrees(repo) if x["name"] == "lr"][0]
    assert st["ahead"] == 1 and st["behind"] == 0 and st["dirty"] == 2

    with pytest.raises(worktrees.WorktreeError, match="uncommitted"):
        worktrees.merge_worktree(repo, "lr")
    worktrees.commit_all(repo, "lr", "more epochs")
    res = worktrees.merge_worktree(repo, "lr")
    assert res["into"] == "main"
    assert (repo.root / "train.py").read_text() == "lr = 0.3\nepochs = 20\n"


def test_merge_conflict_aborts_cleanly(repo):
    a = worktrees.create_worktree(repo, name="a")
    b = worktrees.create_worktree(repo, name="b")
    for w, val in ((a, "0.5"), (b, "0.7")):
        Path(w["path"], "train.py").write_text(f"lr = {val}\nepochs = 10\n")
        worktrees.commit_all(repo, w["name"], f"lr {val}")
    worktrees.merge_worktree(repo, "a")
    with pytest.raises(worktrees.WorktreeError, match="conflict in train.py"):
        worktrees.merge_worktree(repo, "b")
    assert not (repo.root / ".git" / "MERGE_HEAD").exists()
    assert git(repo.root, "status", "--porcelain", "--untracked-files=no") == ""


def test_remove(repo):
    w = worktrees.create_worktree(repo, name="tmp")
    Path(w["path"], "x.txt").write_text("dirty")
    with pytest.raises(worktrees.WorktreeError, match="uncommitted"):
        worktrees.remove_worktree(repo, "tmp")
    r = worktrees.remove_worktree(repo, "tmp", force=True, delete_branch=True)
    assert r["branch_deleted"] and not Path(w["path"]).exists()
    assert "dsd/tmp" not in worktrees.branches(repo)
    assert [x["name"] for x in worktrees.list_worktrees(repo)] == ["main"]
    with pytest.raises(worktrees.WorktreeError):
        worktrees.remove_worktree(repo, "main")


def test_api_claude_session_in_new_worktree(repo):
    with TestClient(create_app([repo.root])) as c:
        t = c.post(f"/api/p/{repo.id}/terminals",
                   json={"kind": "shell", "new_worktree": {"task": "T-1", "task_title": "Write goal"}}).json()
        assert t["worktree"] == "t-1-write-goal" and t["branch"] == "dsd/t-1-write-goal"
        assert t["cwd"].startswith(str(worktrees.base_dir(repo)))
        wts = c.get(f"/api/p/{repo.id}/worktrees").json()
        mine = [w for w in wts if w["name"] == "t-1-write-goal"][0]
        assert mine["terminals"] == [t["id"]]
        # attach a second terminal to the existing worktree
        t2 = c.post(f"/api/p/{repo.id}/terminals", json={"kind": "shell", "worktree": "t-1-write-goal"}).json()
        assert t2["cwd"] == t["cwd"]
        Path(t["cwd"], "train.py").write_text("lr = 1\n")
        ch = c.get(f"/api/p/{repo.id}/changes", params={"worktree": "t-1-write-goal"}).json()
        assert ch["branch"] == "dsd/t-1-write-goal" and ch["files"][0]["path"] == "train.py"
        cm = c.post(f"/api/p/{repo.id}/comments", json={"path": "train.py", "line": 1, "text": "why 1?",
                                                        "worktree": "t-1-write-goal"}).json()
        assert cm["worktree"] == "t-1-write-goal"
        assert c.delete(f"/api/p/{repo.id}/worktrees/t-1-write-goal").status_code == 400  # dirty
        r = c.delete(f"/api/p/{repo.id}/worktrees/t-1-write-goal", params={"force": True, "delete_branch": True})
        assert r.json()["removed"] == "t-1-write-goal"
        assert c.get(f"/api/p/{repo.id}/terminals").json() == []  # its terminals were closed
