import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dsd.cli import app

SKILLS = ["dsd-distill", "dsd-next-task", "dsd-plan", "dsd-report", "dsd-run-experiment"]

FAKE_CLAUDE = """#!/bin/sh
echo "$@" >> "$HOME/claude-calls.log"
if [ "$1 $2" = "mcp add" ]; then
  printf '{"mcpServers": {"dsd": {"type": "stdio", "command": "dsd", "args": ["mcp"]}}}' > "$HOME/.claude.json"
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
    assert calls(home) == ["mcp add -s user dsd -- dsd mcp"]
    assert sorted(p.parent.name for p in (home / ".claude/skills").glob("*/SKILL.md")) == SKILLS
    assert json.loads((home / ".claude.json").read_text())["mcpServers"]["dsd"]["command"] == "dsd"


def test_setup_is_idempotent(home):
    runner = CliRunner()
    assert runner.invoke(app, ["setup"]).exit_code == 0
    skill = home / ".claude/skills/dsd-plan/SKILL.md"
    before = skill.stat().st_mtime_ns
    r = runner.invoke(app, ["setup"])
    assert r.exit_code == 0, r.output
    assert "created" not in r.output and "updated" not in r.output
    assert calls(home) == ["mcp add -s user dsd -- dsd mcp"]
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
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"dsd": {"command": "dsd", "args": ["mcp"]}},
                                                   "other": 1}))
    assert CliRunner().invoke(app, ["setup"]).exit_code == 0
    assert calls(home) == []


def test_setup_without_claude_cli(home, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    r = CliRunner().invoke(app, ["setup"])
    assert r.exit_code == 1
    assert "claude mcp add -s user dsd -- dsd mcp" in r.output
    assert (home / ".claude/skills/dsd-plan/SKILL.md").is_file()
