import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dsd
from dsd import review, worktrees
from dsd.init import init_project
from dsd.project import find_project
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
    p = init_project(root, name="wt-demo").project
    (root / "train.py").write_text("lr = 0.1\nepochs = 10\n")
    (root / ".env").write_text("SECRET=1\n")  # untracked local file worktrees should get a copy of
    (root / ".gitignore").write_text(".env\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    monkeypatch.delenv("DSD_RUN_DIR", raising=False)
    return p


def test_create_list_and_bootstrap(repo):
    w = worktrees.create_worktree(repo, task="T-6", task_title="Add interaction features")
    assert w["name"] == "t-6-add-interaction-features" and w["branch"] == "dsd/t-6-add-interaction-features"
    assert w["base"] == "main" and w["task"] == "T-6"
    path = Path(w["path"])
    assert path.is_dir() and str(path).startswith(str(worktrees.base_dir(repo)))
    assert w["copied"] == [".env"]
    assert (path / ".env").read_text() == "SECRET=1\n"
    assert (repo.data_dir / "worktrees.json").is_file()
    assert git(repo.root, "status", "--porcelain") == ""
    # same name again gets a suffix
    w2 = worktrees.create_worktree(repo, name="t-6-add-interaction-features")
    assert w2["name"] == "t-6-add-interaction-features-2"
    names = [x["name"] for x in worktrees.list_worktrees(repo)]
    assert names[0] == "main" and set(names[1:]) == {w["name"], w2["name"]}


def test_worktree_project_shares_state(repo, monkeypatch):
    w = worktrees.create_worktree(repo, name="exp")
    wp = find_project(Path(w["path"]))
    assert wp.is_worktree and wp.repo == repo.root and wp.id == repo.id
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
    with TestClient(create_app()) as c:
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


def test_only_owned_worktrees_are_listed(repo, tmp_path):
    ours = worktrees.create_worktree(repo, name="ours")
    ext = tmp_path / "external"
    git(repo.root, "worktree", "add", "-q", "-b", "someone-else", str(ext))
    names = [w["name"] for w in worktrees.list_worktrees(repo)]
    assert names == ["main", "ours"]
    cands = worktrees.candidates(repo)
    assert [c["path"] for c in cands] == [str(ext.resolve())]
    assert cands[0]["branch"] == "someone-else" and "dirty" not in cands[0]
    assert worktrees.list_worktrees(repo)[1]["origin"] == "dsd" and ours["origin"] == "dsd"


def test_current_worktree_is_included(repo, tmp_path):
    ext = tmp_path / "external"
    git(repo.root, "worktree", "add", "-q", "-b", "mine", str(ext))
    wts = worktrees.list_worktrees(repo, include=[ext / "sub"])
    assert [(w["name"], w["origin"]) for w in wts] == [("main", "main"), ("external", "current")]
    wts = worktrees.list_worktrees(repo, include=[tmp_path / "unrelated"])
    assert [w["name"] for w in wts] == ["main"]


def test_adopt_and_hide(repo, tmp_path):
    ext = tmp_path / "external"
    git(repo.root, "worktree", "add", "-q", "-b", "feature-x", str(ext))
    w = worktrees.adopt_worktree(repo, str(ext), task="T-3")
    assert w["origin"] == "adopted" and w["name"] == "external" and w["task"] == "T-3" and w["base"] == "main"
    assert [x["name"] for x in worktrees.list_worktrees(repo)] == ["main", "external"]
    assert worktrees.candidates(repo) == []
    with pytest.raises(worktrees.WorktreeError):
        worktrees.adopt_worktree(repo, str(ext))
    with pytest.raises(worktrees.WorktreeError):
        worktrees.adopt_worktree(repo, str(tmp_path))
    worktrees.hide_worktree(repo, "external")
    assert [x["name"] for x in worktrees.list_worktrees(repo)] == ["main"]
    assert ext.is_dir() and "feature-x" in worktrees.branches(repo)


def test_scoped_status_and_changes(repo):
    (repo.root / "apps" / "a").mkdir(parents=True)
    (repo.root / "apps" / "a" / "x.py").write_text("x = 1\n")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "apps")
    from dataclasses import replace

    scoped = replace(repo, scope="apps/a")
    w = worktrees.create_worktree(scoped, name="s")
    Path(w["path"], "train.py").write_text("lr = 2\n")
    Path(w["path"], "apps", "a", "x.py").write_text("x = 2\n")
    Path(w["path"], "apps", "a", "new.py").write_text("y = 1\n")
    st = worktrees.list_worktrees(scoped)[1]
    assert st["dirty"] == 2
    assert worktrees.list_worktrees(repo)[1]["dirty"] == 3
    ch = review.working_changes(scoped, Path(w["path"]), base="main")
    assert sorted(f["path"] for f in ch["files"]) == ["apps/a/new.py", "apps/a/x.py"]
    assert review.change_count(scoped, Path(w["path"])) == 2


def test_untracked_files_are_diffed_without_a_subprocess_each(repo, monkeypatch):
    many = repo.root / "fixtures"
    many.mkdir()
    for i in range(30):
        (many / f"f{i}.json").write_text(f'{{"i": {i}}}\n')
    (many / "blob.bin").write_bytes(b"\x00\x01binary")
    calls = []
    real = review._git
    monkeypatch.setattr(review, "_git", lambda *a, **k: calls.append(a[1:]) or real(*a, **k))
    ch = review.working_changes(repo)
    assert len(calls) < 6
    by = {f["path"]: f for f in ch["files"]}
    assert by["fixtures/f3.json"]["status"] == "added" and by["fixtures/f3.json"]["additions"] == 1
    assert by["fixtures/f3.json"]["hunks"][0]["lines"][0] == {"t": "add", "old": None, "new": 1, "text": '{"i": 3}'}
    assert by["fixtures/blob.bin"]["binary"] and not by["fixtures/blob.bin"]["hunks"]
    assert review.change_count(repo) == 31


def test_api_adopt_candidates_hide(repo, tmp_path):
    ext = tmp_path / "external"
    git(repo.root, "worktree", "add", "-q", "-b", "feature-y", str(ext))
    with TestClient(create_app(current=ext)) as c:
        wts = c.get(f"/api/p/{repo.id}/worktrees").json()
        assert [(w["name"], w["origin"]) for w in wts] == [("main", "main"), ("external", "current")]
        assert c.get(f"/api/p/{repo.id}/worktrees/candidates").json() == []
    with TestClient(create_app()) as c:
        assert [w["name"] for w in c.get(f"/api/p/{repo.id}/worktrees").json()] == ["main"]
        assert [x["branch"] for x in c.get(f"/api/p/{repo.id}/worktrees/candidates").json()] == ["feature-y"]
        w = c.post(f"/api/p/{repo.id}/worktrees/adopt", json={"path": str(ext)}).json()
        assert w["origin"] == "adopted"
        assert c.post(f"/api/p/{repo.id}/worktrees/external/hide").status_code == 200
        assert [w["name"] for w in c.get(f"/api/p/{repo.id}/worktrees").json()] == ["main"]


def test_changes_respect_a_total_line_budget(repo, monkeypatch):
    monkeypatch.setattr(review, "MAX_TOTAL_LINES", 25)
    for i in range(3):
        (repo.root / f"big{i}.txt").write_text("".join(f"line {n}\n" for n in range(10)))
    files = {f["path"]: f for f in review.working_changes(repo)["files"]}
    assert [len(files[f"big{i}.txt"]["hunks"]) for i in range(3)] == [1, 1, 0]
    assert files["big2.txt"]["truncated"] and files["big2.txt"]["additions"] == 10


def test_overview_counts_changes_for_a_worktree(repo, tmp_path):
    w = worktrees.create_worktree(repo, name="focus")
    Path(w["path"], "train.py").write_text("lr = 3\n")
    git(Path(w["path"]), "commit", "-qam", "lr")
    Path(w["path"], "notes.txt").write_text("n\n")
    Path(w["path"], ".env").write_text("SECRET=1\n")
    ext = tmp_path / "external"
    git(repo.root, "worktree", "add", "-q", "-b", "mine", str(ext))
    with TestClient(create_app(current=ext)) as c:
        main = c.get(f"/api/p/{repo.id}/overview").json()
        assert main["changes"] == 0 and main["current_worktree"] == "external"
        focused = c.get(f"/api/p/{repo.id}/overview", params={"worktree": "focus"}).json()
        ch = c.get(f"/api/p/{repo.id}/changes", params={"worktree": "focus"}).json()
        assert focused["changes"] == len(ch["files"]) == 2


def test_api_move_worktree_takes_its_sessions(repo):
    from dsd.init import init_project

    other = init_project(repo.root, name="staff-on-floor").project
    with TestClient(create_app()) as c:
        t = c.post(f"/api/p/{repo.id}/terminals", json={"kind": "shell", "new_worktree": {"name": "sof"}}).json()
        r = c.post(f"/api/p/{repo.id}/worktrees/sof/move", json={"to": other.id})
        assert r.status_code == 200 and r.json()["name"] == "sof"
        assert c.get(f"/api/p/{repo.id}/terminals").json() == []
        assert [x["id"] for x in c.get(f"/api/p/{other.id}/terminals").json()] == [t["id"]]
        assert [w["name"] for w in c.get(f"/api/p/{other.id}/worktrees").json()] == ["main", "sof"]
        assert [w["name"] for w in c.get(f"/api/p/{repo.id}/worktrees").json()] == ["main"]
        new = c.post("/api/projects", json={"path": str(repo.root), "init": True, "name": "third"}).json()
        assert new["name"] == "third" and new["id"] not in (repo.id, other.id)


def test_overview_current_worktree_includes_owned_ones(repo):
    w = worktrees.create_worktree(repo, name="mine")
    with TestClient(create_app(current=Path(w["path"]))) as c:
        assert c.get(f"/api/p/{repo.id}/overview").json()["current_worktree"] == "mine"


def test_relevant_branches_only(repo):
    for i in range(5):
        git(repo.root, "branch", f"unrelated-{i}")
    worktrees.create_worktree(repo, name="mine")
    assert worktrees.default_branch(repo) == "main"
    assert worktrees.relevant_branches(repo) == ["main", "dsd/mine"]
    with TestClient(create_app()) as c:
        b = c.get(f"/api/p/{repo.id}/branches").json()
        assert b == {"current": "main", "default": "main", "branches": ["main", "dsd/mine"]}


def test_rename_worktree_and_branch(repo, tmp_path):
    w = worktrees.create_worktree(repo)
    assert w["auto_named"] is True and w["branch_pushed"] is False
    Path(w["path"], "train.py").write_text("lr = 9\n")
    cm = review.add_comment(repo, "train.py", 1, "hm", worktree=w["name"])
    r = worktrees.rename_worktree(repo, w["name"], "Rules aware target", rename_branch=True)
    assert r["name"] == "rules-aware-target" and r["branch"] == "dsd/rules-aware-target" and r["auto_named"] is False
    assert r["path"] == w["path"] and Path(w["path"], "train.py").read_text() == "lr = 9\n"
    assert git(Path(w["path"]), "branch", "--show-current").strip() == "dsd/rules-aware-target"
    assert w["branch"] not in worktrees.branches(repo)
    assert next(c for c in review.load_comments(repo) if c["id"] == cm["id"])["worktree"] == "rules-aware-target"
    label_only = worktrees.rename_worktree(repo, "rules-aware-target", "Second name")
    assert label_only["name"] == "second-name" and label_only["branch"] == "dsd/rules-aware-target"
    other = worktrees.create_worktree(repo, name="taken")
    with pytest.raises(worktrees.WorktreeError, match="already"):
        worktrees.rename_worktree(repo, "second-name", "taken")
    with pytest.raises(worktrees.WorktreeError):
        worktrees.rename_worktree(repo, "main", "x")
    assert other["auto_named"] is False


def test_pushed_branches_are_not_renamed(repo, tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo.root, "remote", "add", "origin", str(remote))
    w = worktrees.create_worktree(repo, name="pushed")
    git(Path(w["path"]), "push", "-q", "-u", "origin", "dsd/pushed")
    assert worktrees.get_worktree(repo, "pushed")["branch_pushed"] is True
    with pytest.raises(worktrees.WorktreeError, match="pushed"):
        worktrees.rename_worktree(repo, "pushed", "new name", rename_branch=True)
    assert worktrees.rename_worktree(repo, "pushed", "new name")["branch"] == "dsd/pushed"


def test_api_rename_updates_open_sessions(repo):
    with TestClient(create_app()) as c:
        t = c.post(f"/api/p/{repo.id}/terminals", json={"kind": "shell", "new_worktree": {}}).json()
        old = t["worktree"]
        worktrees.rename_worktree(repo, old, "named elsewhere", rename_branch=True)
        mine = c.get(f"/api/p/{repo.id}/terminals").json()[0]
        assert mine["worktree"] == "named-elsewhere" and mine["branch"] == "dsd/named-elsewhere"
        r = c.post(f"/api/p/{repo.id}/worktrees/named-elsewhere/rename", json={"name": "via api"})
        assert r.status_code == 200 and r.json()["name"] == "via-api"
        assert c.get(f"/api/p/{repo.id}/terminals").json()[0]["worktree"] == "via-api"


@pytest.fixture
def stale_main(repo, tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo.root, "remote", "add", "origin", str(remote))
    git(repo.root, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    for i in range(3):
        (other / f"merged_{i}.py").write_text(f"x = {i}\n")
        git(other, "add", "-A")
        git(other, "commit", "-qm", f"merged PR {i}")
    git(other, "push", "-q", "origin", "main")
    return repo


def test_new_worktrees_start_from_the_latest_remote_main(stale_main):
    repo = stale_main
    w = worktrees.create_worktree(repo, name="fresh")
    remote_head = git(repo.root, "rev-parse", "origin/main").strip()
    assert git(Path(w["path"]), "rev-parse", "HEAD").strip() == remote_head
    assert git(repo.root, "rev-parse", "main").strip() != remote_head
    st = worktrees.list_worktrees(repo)[1]
    assert st["base_ref"] == "origin/main" and st["ahead"] == 0 and st["behind"] == 0
    assert st["base_stale"] == 3
    ch = review.working_changes(repo, Path(w["path"]), base="main")
    assert ch["files"] == [] and ch["base"] == "origin/main"
    assert review.change_count(repo, Path(w["path"]), base="main") == 0


def test_worktrees_on_local_main_still_compare_with_local_main(stale_main):
    repo = stale_main
    w = worktrees.create_worktree(repo, name="old", base="main", fetch=False)
    Path(w["path"], "train.py").write_text("lr = 5\n")
    git(Path(w["path"]), "commit", "-qam", "tweak")
    git(repo.root, "fetch", "-q", "origin")
    st = next(x for x in worktrees.list_worktrees(repo) if x["name"] == "old")
    assert st["ahead"] == 1 and st["base_ref"] in ("main", "origin/main")
    ch = review.working_changes(repo, Path(w["path"]), base="main")
    assert [f["path"] for f in ch["files"]] == ["train.py"]
