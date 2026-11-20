import subprocess
import time

import pytest
from fastapi.testclient import TestClient

import dsd
from dsd.init import init_project
from dsd.web.server import create_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DSD_HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    p = init_project(root, name="demo").project
    (root / "README.md").write_text("demo\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=root, check=True)
    monkeypatch.setenv("DSD_PROJECT_ROOT", str(root))
    monkeypatch.delenv("DSD_RUN_DIR", raising=False)
    for s in range(2):
        with dsd.run(f"xgb-{s}", benchmark="b1", params={"model": "xgb", "seed": s}) as r:
            r.log({"loss": 1.0}, step=0)
            r.log({"loss": 0.5}, step=1)
            r.log({"auc": 0.8 + s / 100})
            r.html("report.html", "<h1>report</h1>")
    with TestClient(create_app()) as client:  # one event loop for the whole test (PTY readers live on it)
        yield client, p


def test_projects_and_overview(env):
    c, p = env
    projects = c.get("/api/projects").json()
    assert [x["name"] for x in projects] == ["demo"]
    ov = c.get(f"/api/p/{p.id}/overview").json()
    assert ov["plans"][0]["slug"] == "main" and len(ov["recent_runs"]) == 2
    assert c.get("/api/p/nope/overview").status_code == 404


def test_tasks_api(env):
    c, p = env
    t = c.post(f"/api/p/{p.id}/tasks", json={"title": "Try lgbm", "tags": ["exp"]}).json()
    assert t["id"] == "T-2"
    t = c.patch(f"/api/p/{p.id}/tasks/T-2", json={"status": "doing", "note": "go"}).json()
    assert t["status"] == "doing" and t["notes"] == ["→ go"]
    assert "[/] T-2 Try lgbm" in p.main_plan_path.read_text()
    detail = c.get(f"/api/p/{p.id}/tasks/T-2").json()
    assert detail["runs"] == [] and detail["commits"] == []
    assert c.patch(f"/api/p/{p.id}/tasks/T-99", json={"status": "done"}).status_code == 400
    assert c.post(f"/api/p/{p.id}/plans", json={"slug": "eval"}).status_code == 200
    assert [x["slug"] for x in c.get(f"/api/p/{p.id}/plans").json()] == ["main", "eval"]


def test_docs_api(env):
    c, p = env
    assert c.put(f"/api/p/{p.id}/docs/file", json={"path": "notes/a.md", "content": "# Alpha beta"}).status_code == 200
    assert c.get(f"/api/p/{p.id}/docs/file", params={"path": "notes/a.md"}).json()["content"] == "# Alpha beta"
    assert c.get(f"/api/p/{p.id}/docs/search", params={"q": "alpha"}).json()[0]["path"] == "notes/a.md"
    assert c.get(f"/api/p/{p.id}/docs/file", params={"path": "../../etc/passwd"}).status_code == 400
    assert c.get(f"/api/p/{p.id}/docs/raw/notes/a.md").text == "# Alpha beta"


def test_runs_api(env):
    c, p = env
    runs = c.get(f"/api/p/{p.id}/runs", params={"sort": "-metrics.auc", "where": ["params.seed>=0"]}).json()
    assert [r["name"] for r in runs] == ["xgb-1", "xgb-0"]
    rid = runs[0]["id"]
    d = c.get(f"/api/p/{p.id}/runs/{rid[-8:]}").json()
    assert d["series"]["loss"] == [[0, 1.0], [1, 0.5]]
    assert c.get(f"/api/p/{p.id}/runs/{rid}/artifacts/report.html").text == "<h1>report</h1>"
    assert c.get(f"/api/p/{p.id}/runs/{rid}/artifacts/../run.json").status_code == 404
    cmp_ = c.get(f"/api/p/{p.id}/compare", params={"ids": f"{runs[0]['id']},{runs[1]['id']}"}).json()
    assert {x["key"] for x in cmp_["params"] if x["differs"]} == {"seed"}
    c.put(f"/api/p/{p.id}/benchmarks/b1", json={"primary": "auc", "direction": "max"})
    board = c.get(f"/api/p/{p.id}/benchmarks/b1", params={"group_by": "params.model"}).json()
    assert board["rows"][0]["group"] == "xgb" and board["rows"][0]["n"] == 2
    assert c.get(f"/api/p/{p.id}/benchmarks").json()[0]["spec"]["primary"] == "auc"


def test_changes_and_comments(env):
    c, p = env
    (p.root / "train.py").write_text("print('hi')\nx = 1\n")
    (p.root / "README.md").write_text((p.root / "README.md").read_text() + "\nextra line\n")
    ch = c.get(f"/api/p/{p.id}/changes").json()
    by_path = {f["path"]: f for f in ch["files"]}
    assert by_path["train.py"]["status"] == "added" and by_path["train.py"]["additions"] == 2
    assert set(by_path) == {"train.py", "README.md"}
    assert by_path["README.md"]["status"] == "modified"
    added = [ln for h in by_path["README.md"]["hunks"] for ln in h["lines"] if ln["t"] == "add"]
    assert added[-1]["text"] == "extra line"
    commits = c.get(f"/api/p/{p.id}/commits").json()
    assert commits[0]["subject"] == "init"
    assert c.get(f"/api/p/{p.id}/changes", params={"ref": commits[0]["short"]}).json()["files"]
    cm = c.post(f"/api/p/{p.id}/comments", json={"path": "train.py", "line": 2, "text": "use a better name", "code": "x = 1"}).json()
    assert cm["status"] == "open"
    assert len(c.get(f"/api/p/{p.id}/comments").json()) == 1

    term = c.post(f"/api/p/{p.id}/terminals", json={"kind": "shell", "command": "cat"}).json()
    with c.websocket_connect(f"/api/terminals/{term['id']}/ws") as ws:
        time.sleep(0.2)
        r = c.post(f"/api/p/{p.id}/comments/send", json={"terminal_id": term["id"]})
        assert r.json() == {"sent": 1}
        seen = b""
        deadline = time.time() + 10
        while b"use a better name" not in seen and time.time() < deadline:
            seen += ws.receive_bytes()
        assert b"train.py:2" in seen
    assert c.get(f"/api/p/{p.id}/comments").json()[0]["status"] == "sent"
    c.delete(f"/api/terminals/{term['id']}")
    assert c.get(f"/api/p/{p.id}/terminals").json() == []


def test_terminal_roundtrip(env):
    c, p = env
    term = c.post(f"/api/p/{p.id}/terminals", json={"kind": "shell"}).json()
    with c.websocket_connect(f"/api/terminals/{term['id']}/ws") as ws:
        ws.send_text('{"type":"resize","rows":30,"cols":100}')
        ws.send_bytes(b"echo dsd-$((40+2))\r")
        seen = b""
        deadline = time.time() + 15
        while b"dsd-42" not in seen and time.time() < deadline:
            seen += ws.receive_bytes()
        assert b"dsd-42" in seen
    c.delete(f"/api/terminals/{term['id']}")


def test_add_project_starts_one_outside_the_repo(env, tmp_path):
    c, _ = env
    other = tmp_path / "other"
    (other / "apps" / "x").mkdir(parents=True)
    assert c.post("/api/projects", json={"path": str(other)}).status_code == 409
    assert c.post("/api/projects", json={"path": str(other), "init": True, "scope": "nope"}).status_code == 400
    p = c.post("/api/projects", json={"path": str(other), "init": True, "scope": "apps/x"}).json()
    assert p["scope"] == "apps/x" and p["name"] == "x" and p["repo"] == str(other.resolve())
    assert sorted(other.rglob("*")) == [other / "apps", other / "apps" / "x"]
    assert c.post("/api/projects", json={"path": str(other / "apps" / "x")}).json()["id"] == p["id"]


def test_delete_task_with_subtasks(env):
    c, p = env
    parent = c.post(f"/api/p/{p.id}/tasks", json={"title": "Parent"}).json()
    child = c.post(f"/api/p/{p.id}/tasks", json={"title": "Child", "parent": parent["id"]}).json()
    keep = c.post(f"/api/p/{p.id}/tasks", json={"title": "Keep me"}).json()
    c.patch(f"/api/p/{p.id}/tasks/{parent['id']}", json={"note": "a note"})
    r = c.delete(f"/api/p/{p.id}/tasks/{parent['id']}")
    assert r.status_code == 200 and r.json() == {"deleted": [parent["id"], child["id"]]}
    ids = [t["id"] for t in c.get(f"/api/p/{p.id}/tasks").json()]
    assert parent["id"] not in ids and child["id"] not in ids and keep["id"] in ids
    assert "a note" not in p.main_plan_path.read_text()
    assert c.delete(f"/api/p/{p.id}/tasks/T-404").status_code == 400
