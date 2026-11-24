import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dsd import agents
from dsd.cli import app

ADD = "mcp add -s user dsd -- " + " ".join(agents.mcp_command())

SKILLS = ["dsd-benchmark", "dsd-develop", "dsd-distill", "dsd-plan", "dsd-report", "dsd-results", "dsd-review", "dsd-run-experiment"]

FAKE_CLAUDE = """#!/bin/sh
echo "$@" >> "$HOME/claude-calls.log"
if [ "$1 $2" = "mcp add" ]; then
  shift 6
  printf '{"mcpServers": {"dsd": {"type": "stdio", "command": "%s", "args": ["%s"]}}}' "$1" "$2" > "$HOME/.claude.json"
fi
if [ "$1 $2" = "mcp remove" ]; then
  printf '{"mcpServers": {}}' > "$HOME/.claude.json"
fi
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    h.mkdir()
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return h


def calls(home: Path) -> list[str]:
    log = home / "claude-calls.log"
    return log.read_text().splitlines() if log.exists() else []


def test_setup_registers_mcp_and_installs_skills(home):
    r = CliRunner().invoke(app, ["setup"])
    assert r.exit_code == 0, r.output
    assert calls(home) == [ADD]
    assert sorted(p.parent.name for p in (home / ".claude/skills").glob("*/SKILL.md")) == SKILLS
    assert json.loads((home / ".claude.json").read_text())["mcpServers"]["dsd"]["command"] == agents.dsd_executable()
    assert agents.mcp_status()["state"] == "connected"


def test_setup_is_idempotent(home):
    runner = CliRunner()
    assert runner.invoke(app, ["setup"]).exit_code == 0
    skill = home / ".claude/skills/dsd-plan/SKILL.md"
    before = skill.stat().st_mtime_ns
    r = runner.invoke(app, ["setup"])
    assert r.exit_code == 0, r.output
    assert "created" not in r.output and "updated" not in r.output
    assert calls(home) == [ADD]
    assert skill.stat().st_mtime_ns == before


def test_setup_keeps_edited_skills_unless_forced(home):
    runner = CliRunner()
    runner.invoke(app, ["setup"])
    skill = home / ".claude/skills/dsd-plan/SKILL.md"
    skill.write_text("custom")
    r = runner.invoke(app, ["setup"])
    assert r.exit_code == 0 and "kept" in r.output
    assert skill.read_text() == "custom"
    assert runner.invoke(app, ["setup", "--force"]).exit_code == 0
    assert skill.read_text() != "custom"


def test_setup_skips_mcp_add_when_already_registered(home):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"dsd": {"command": agents.dsd_executable(), "args": ["mcp"]}},
                                                   "other": 1}))
    assert CliRunner().invoke(app, ["setup"]).exit_code == 0
    assert calls(home) == []


def test_setup_replaces_a_registration_that_points_at_another_dsd(home):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"dsd": {"command": "/old/checkout/dsd", "args": ["mcp"]}}}))
    assert agents.mcp_status()["state"] == "stale"
    r = CliRunner().invoke(app, ["setup"])
    assert r.exit_code == 0 and "updated" in r.output, r.output
    assert calls(home) == ["mcp remove -s user dsd", ADD]
    assert agents.mcp_status()["state"] == "connected"


def test_skills_refresh_only_for_users_who_installed_them(home):
    assert agents.refresh_installed_skills() == []
    assert not (home / ".claude/skills").exists()
    agents.install_skills()
    (home / ".claude/skills/dsd-results").rename(home / "gone")
    edited = home / ".claude/skills/dsd-plan/SKILL.md"
    edited.write_text("mine")
    actions = agents.refresh_installed_skills()
    assert [p.name for a, p in actions if a == "created"] == ["dsd-results"]
    assert edited.read_text() == "mine"


def test_setup_without_claude_cli(home, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(agents, "installed_claude", lambda: None)
    monkeypatch.setattr(agents, "login_shell_claude", lambda: None)
    r = CliRunner().invoke(app, ["setup"])
    assert r.exit_code == 1
    assert " ".join(["claude", ADD]) in r.output
    assert (home / ".claude/skills/dsd-plan/SKILL.md").is_file()



def test_setup_finds_claude_outside_path(home, monkeypatch):
    claude = home / ".local/bin/claude"
    claude.parent.mkdir(parents=True)
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(agents, "login_shell_claude", lambda: None)
    r = CliRunner().invoke(app, ["setup"])
    assert r.exit_code == 0, r.output
    assert calls(home) == [ADD]
    status = agents.mcp_status()
    assert status["state"] == "connected" and status["claude_cli"]

def test_setup_installs_whole_skill_folders(home):
    assert CliRunner().invoke(app, ["setup"]).exit_code == 0
    plan = home / ".claude/skills/dsd-plan"
    assert (plan / "references/conventions.md").is_file() and (plan / "templates/plan.md").is_file()
    assert (home / ".claude/skills/dsd-review/assets/explainer.html").is_file()
    assert json.loads((plan / ".dsd-managed").read_text())["SKILL.md"]


def test_setup_updates_unedited_skills_from_an_older_dsd(home):
    from dsd import agents

    runner = CliRunner()
    runner.invoke(app, ["setup"])
    plan = home / ".claude/skills/dsd-plan"
    old = "old version"
    (plan / "SKILL.md").write_text(old)
    manifest = json.loads((plan / ".dsd-managed").read_text())
    manifest["SKILL.md"] = agents._sha(old.encode())
    (plan / ".dsd-managed").write_text(json.dumps(manifest))
    assert agents.skill_state("dsd-plan", agents.bundled_skills()["dsd-plan"]) == "outdated"
    r = runner.invoke(app, ["setup"])
    assert "updated" in r.output and (plan / "SKILL.md").read_text() != old
    assert agents.skill_state("dsd-plan", agents.bundled_skills()["dsd-plan"]) == "current"


def test_explainer_guide_is_the_same_in_develop_and_review():
    from dsd import agents

    skills = agents.bundled_skills()
    for rel in ("references/explainer.md", "assets/explainer.html"):
        assert skills["dsd-develop"][rel] == skills["dsd-review"][rel] == skills["dsd-plan"][rel], rel


def test_bundled_skills_have_frontmatter_and_no_personal_names():
    from dsd import agents, skills

    for name, files in agents.bundled_skills().items():
        meta = skills._frontmatter(files["SKILL.md"].decode())
        assert meta["name"] == name and len(meta["description"]) > 80, name
        for rel, data in files.items():
            assert b"Francis" not in data and b"Nory" not in data, (name, rel)


def test_claude_sessions_from_the_app_get_dsd_without_setup(home):
    cmd = agents.claude_session_command("claude")
    assert cmd.startswith("claude --mcp-config ") and cmd.endswith("mcp.json")
    path = Path(cmd.split(" ", 2)[2])
    server = json.loads(path.read_text())["mcpServers"]["dsd"]
    assert server["command"] == agents.dsd_executable() and server["args"] == ["mcp"]
    assert sorted(p.parent.name for p in (home / ".claude/skills").glob("*/SKILL.md")) == SKILLS
    CliRunner().invoke(app, ["setup"])
    assert agents.claude_session_command("claude") == "claude"


def test_claude_api_status_and_connect(home):
    from fastapi.testclient import TestClient

    from dsd.web.server import create_app

    with TestClient(create_app()) as c:
        s = c.get("/api/claude").json()
        assert s["mcp"]["state"] == "missing" and {x["state"] for x in s["skills"]} == {"missing"}
        r = c.post("/api/claude/connect", json={}).json()
        assert r["mcp"] == "created" and r["status"]["state"] == "connected"
        assert {x["state"] for x in c.get("/api/claude").json()["skills"]} == {"current"}
