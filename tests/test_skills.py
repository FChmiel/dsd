import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dsd import skills
from dsd.init import init_project
from dsd.web.server import create_app


def skill(d: Path, name: str, description: str, extra: dict[str, str] | None = None) -> Path:
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n")
    for rel, text in (extra or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("HOME", str(h))
    s = h / ".claude" / "skills"
    skill(s / "work-order", "work-order", "Write work orders: plans of small PRs.",
          {"references/conventions.md": "# Conventions\n", "templates/overview.md": "# Overview\n"})
    skill(s / "pane", "pane", "Use Pane.")
    (s / "pane" / ".pane-managed").write_text("x")
    skill(s / "synced" / "bucket" / "docx", "docx", "Word documents.")
    (s / "synced" / "bucket" / "manifest.json").write_text("{}")
    plug = h / ".claude" / "plugins"
    skill(plug / "cache" / "mk" / "tool" / "1.0" / "skills" / "rlm", "rlm", "Big codebases.")
    plug.mkdir(parents=True, exist_ok=True)
    (plug / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"tool@mk": [{"installPath": str(plug / "cache" / "mk" / "tool" / "1.0"), "scope": "user"}]}}))
    repo = tmp_path / "repo"
    skill(repo / ".claude" / "skills" / "omni", "omni-dashboards", "Build Omni dashboards: with colons.")
    init_project(repo, name="nory")
    init_project(repo, name="staff-on-floor")
    return h


def test_lists_skills_by_source(home):
    found = {s["name"]: s for s in skills.list_skills()}
    assert set(found) == {"work-order", "pane", "docx", "rlm", "omni-dashboards"}
    assert [(found[n]["source"], found[n]["editable"]) for n in ("work-order", "pane", "docx", "rlm", "omni-dashboards")] == [
        ("user", True), ("pane", False), ("claude.ai", False), ("plugin", False), ("repo", True)]
    assert found["work-order"]["description"] == "Write work orders: plans of small PRs."
    assert found["work-order"]["files"] == 3
    assert found["rlm"]["plugin"] == "tool@mk"
    assert found["omni-dashboards"]["description"] == "Build Omni dashboards: with colons."
    assert found["omni-dashboards"]["projects"] == ["nory", "staff-on-floor"]


def test_read_and_edit_files(home):
    wo = next(s for s in skills.list_skills() if s["name"] == "work-order")
    detail = skills.get_skill(wo["id"])
    assert [f["path"] for f in detail["files"]] == ["SKILL.md", "references/conventions.md", "templates/overview.md"]
    assert skills.read_file(wo["id"], "references/conventions.md") == "# Conventions\n"
    skills.write_file(wo["id"], "references/conventions.md", "# Better\n")
    skills.write_file(wo["id"], "templates/new.md", "# New\n")
    assert (Path(wo["path"]) / "templates" / "new.md").read_text() == "# New\n"
    with pytest.raises(skills.SkillError):
        skills.read_file(wo["id"], "../pane/SKILL.md")
    with pytest.raises(skills.SkillError):
        skills.write_file(wo["id"], "run.exe", "x")
    pane = next(s for s in skills.list_skills() if s["name"] == "pane")
    with pytest.raises(skills.SkillError):
        skills.write_file(pane["id"], "SKILL.md", "hacked")
    with pytest.raises(KeyError):
        skills.get_skill("nope")


def test_skills_api(home):
    with TestClient(create_app()) as c:
        listed = c.get("/api/skills").json()
        wo = next(s for s in listed if s["name"] == "work-order")
        assert c.get(f"/api/skills/{wo['id']}").json()["files"][0]["path"] == "SKILL.md"
        assert "# work-order" in c.get(f"/api/skills/{wo['id']}/file", params={"path": "SKILL.md"}).json()["content"]
        assert c.put(f"/api/skills/{wo['id']}/file", json={"path": "SKILL.md", "content": "# v2\n"}).status_code == 200
        assert (Path(wo["path"]) / "SKILL.md").read_text() == "# v2\n"
        pane = next(s for s in listed if s["name"] == "pane")
        assert c.put(f"/api/skills/{pane['id']}/file", json={"path": "SKILL.md", "content": "x"}).status_code == 400
        assert c.get("/api/skills/nope").status_code == 404
        t = c.post(f"/api/skills/{wo['id']}/session", json={"kind": "shell"}).json()
        assert t["cwd"] == wo["path"] and t["project_id"] == "skills"
        assert [x["id"] for x in c.get("/api/skills/terminals").json()] == [t["id"]]
