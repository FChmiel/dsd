import os
import time

from typer.testing import CliRunner

from dsd import backup as bk
from dsd.cli import app
from dsd.init import init_project
from dsd.project import find_project


def test_local_snapshots_hardlink_and_restore(tmp_path):
    proj_dir, store = tmp_path / "proj", tmp_path / "store"
    proj_dir.mkdir()
    p = init_project(proj_dir).project
    bk.add_local_target(p, str(store))
    p = find_project(proj_dir)
    (p.docs_path / "notes/a.md").write_text("A")
    t = bk.targets(p)[0]
    r1 = t.push(p, bk.include_paths(p, p.backup[0]))
    assert r1.copied == r1.files and r1.files >= 3
    time.sleep(1.1)
    (p.docs_path / "notes/b.md").write_text("B")
    r2 = t.push(p, bk.include_paths(p, p.backup[0]))
    assert r2.copied == 1 and r2.linked == r1.files
    same = os.stat(r1.location / "docs/notes/a.md").st_ino == os.stat(r2.location / "docs/notes/a.md").st_ino
    assert same
    assert [s.name for s in t.list_snapshots(p)] == [r1.snapshot, r2.snapshot]
    out = tmp_path / "restored"
    t.restore(p, r1.snapshot, out)
    assert (out / "docs/notes/a.md").read_text() == "A" and not (out / "docs/notes/b.md").exists()


def test_cli_backup(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    init_project(tmp_path / "proj")
    monkeypatch.chdir(tmp_path / "proj")
    r = CliRunner()
    assert r.invoke(app, ["backup"]).exit_code == 1  # no target yet
    assert r.invoke(app, ["backup", "add-local", str(tmp_path / "store")]).exit_code == 0
    res = r.invoke(app, ["backup"])
    assert res.exit_code == 0 and "snapshot" in res.output, res.output
    assert "1 snapshots" in r.invoke(app, ["backup", "ls"]).output
