import subprocess
import tomllib
from pathlib import Path

import pytest

from dsd.init import init_project
from dsd.project import ProjectNotFound, all_projects, dsd_home, find_project


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "monorepo"
    (root / "apps" / "churn" / "src").mkdir(parents=True)
    (root / "apps" / "pricing").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    (root / "README.md").write_text("hi\n")
    (root / "apps" / "churn" / "src" / "train.py").write_text("print(1)\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_init_writes_nothing_to_the_repo(repo):
    before, status = snapshot(repo), git(repo, "status", "--porcelain")
    report = init_project(repo, name="churn")
    assert snapshot(repo) == before
    assert git(repo, "status", "--porcelain") == status

    p = report.project
    assert p.data_dir == dsd_home() / "projects" / p.id
    data = tomllib.loads((p.data_dir / "project.toml").read_text())
    assert data["id"] == p.id and data["name"] == "churn" and data["repo"] == str(repo.resolve())
    assert "scope" not in data
    assert p.main_plan_path == p.data_dir / "docs" / "plans" / "main.md" and p.main_plan_path.is_file()
    assert p.runs_path == p.data_dir / "runs" and p.runs_path.is_dir()
    assert p.index_path == p.data_dir / "index.db"


def test_init_is_idempotent_per_repo_and_scope(repo):
    first = init_project(repo, name="churn")
    again = init_project(repo)
    assert again.project.id == first.project.id and again.project.name == "churn"
    assert not again.changed
    assert init_project(repo, name="churn").project.id == first.project.id
    scoped = init_project(repo, scope="apps/churn")
    assert scoped.project.id != first.project.id
    assert [p.id for p in all_projects()] == sorted([first.project.id, scoped.project.id])


def test_init_resolves_subdir_and_worktree_to_main_checkout(repo, tmp_path):
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    a = init_project(wt / "apps")
    b = init_project(repo)
    assert a.project.id == b.project.id
    assert a.project.repo == repo.resolve()


def test_init_rejects_bad_scope(repo):
    with pytest.raises(ValueError):
        init_project(repo, scope="does/not/exist")
    with pytest.raises(ValueError):
        init_project(repo, scope="../elsewhere")


def test_find_from_root_subdir_and_linked_worktree(repo, tmp_path):
    pid = init_project(repo, name="mono").project.id
    assert find_project(repo).id == pid
    assert find_project(repo / "apps" / "churn" / "src").id == pid
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    p = find_project(wt / "apps" / "churn")
    assert p.id == pid
    assert p.root == wt.resolve() and p.repo == repo.resolve() and p.is_worktree
    assert not find_project(repo).is_worktree


def test_most_specific_scope_wins(repo, tmp_path):
    whole = init_project(repo, name="mono").project.id
    churn = init_project(repo, name="churn", scope="apps/churn").project.id
    assert find_project(repo / "apps" / "churn" / "src").id == churn
    assert find_project(repo / "apps" / "churn").id == churn
    assert find_project(repo / "apps" / "pricing").id == whole
    assert find_project(repo).id == whole
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    assert find_project(wt / "apps" / "churn" / "src").id == churn
    assert find_project(wt / "apps" / "churn").work_dir == wt.resolve() / "apps" / "churn"


def test_scoped_project_only_covers_its_scope(repo):
    init_project(repo, scope="apps/churn")
    with pytest.raises(ProjectNotFound):
        find_project(repo / "apps" / "pricing")
    with pytest.raises(ProjectNotFound):
        find_project(repo)


def test_find_from_inside_the_data_dir(repo):
    p = init_project(repo).project
    found = find_project(p.data_dir / "docs" / "plans")
    assert found.id == p.id and found.root == repo.resolve()


def test_plain_folder_without_git(tmp_path):
    folder = tmp_path / "notebooks"
    (folder / "sub").mkdir(parents=True)
    pid = init_project(folder).project.id
    assert find_project(folder / "sub").id == pid
    assert not any(folder.rglob("*.toml"))


def test_not_found_outside_any_project(repo, tmp_path):
    init_project(repo)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ProjectNotFound):
        find_project(other)


def test_several_named_projects_on_one_repo(repo):
    first = init_project(repo, name="mono").project
    work = init_project(repo, name="staff-on-floor").project
    assert work.id != first.id and work.repo == first.repo and work.scope is None
    assert init_project(repo, name="staff-on-floor").project.id == work.id
    assert init_project(repo).project.id == first.id
    assert find_project(repo).id == first.id
    assert find_project(repo / "apps" / "churn").id == first.id


def test_set_default_changes_the_main_checkout_project(repo):
    from dsd.init import set_default

    first = init_project(repo, name="mono").project
    work = init_project(repo, name="staff-on-floor").project
    set_default(work)
    assert find_project(repo).id == work.id
    assert init_project(repo).project.id == work.id
    set_default(first)
    assert find_project(repo).id == first.id
    assert [p.default for p in all_projects()] == [True, False]


def test_worktree_owner_wins_over_the_default(repo):
    from dsd import worktrees

    init_project(repo, name="mono")
    work = init_project(repo, name="staff-on-floor").project
    w = worktrees.create_worktree(work, name="sof")
    p = find_project(Path(w["path"]) / "apps" / "churn")
    assert p.id == work.id and p.root == Path(w["path"]) and p.is_worktree


def test_move_worktree_between_projects(repo, tmp_path):
    from dsd import worktrees

    mono = init_project(repo, name="mono").project
    work = init_project(repo, name="staff-on-floor").project
    w = worktrees.create_worktree(mono, name="sof")
    assert find_project(Path(w["path"])).id == mono.id
    moved = worktrees.move_worktree(mono, "sof", work)
    assert moved["name"] == "sof" and moved["origin"] == "dsd"
    assert find_project(Path(w["path"])).id == work.id
    assert [x["name"] for x in worktrees.list_worktrees(mono)] == ["main"]
    assert [x["name"] for x in worktrees.list_worktrees(work)] == ["main", "sof"]
    assert worktrees.candidates(mono) == []
    assert [x["name"] for x in worktrees.list_worktrees(mono, include=[Path(w["path"])])] == ["main"]
    (tmp_path / "elsewhere").mkdir()
    other = init_project(tmp_path / "elsewhere").project
    with pytest.raises(worktrees.WorktreeError):
        worktrees.move_worktree(work, "sof", other)
