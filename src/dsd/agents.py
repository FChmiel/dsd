"""`dsd setup`: wire dsd into Claude Code for the user, outside any repo.

Registers the dsd MCP server in user scope (`claude mcp add -s user dsd -- dsd mcp`) and installs the
dsd skills into ~/.claude/skills. Idempotent; skills the user has edited are kept unless forced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

MCP_NAME = "dsd"
MCP_COMMAND = ["dsd", "mcp"]


def claude_dir() -> Path:
    return Path.home() / ".claude"


def install_skills(force: bool = False) -> list[tuple[str, Path]]:
    actions = []
    src = files("dsd.templates").joinpath("skills")
    for skill in sorted(src.iterdir(), key=lambda s: s.name):
        if not skill.is_dir():
            continue
        content = skill.joinpath("SKILL.md").read_text()
        dest = claude_dir() / "skills" / skill.name / "SKILL.md"
        if dest.exists() and dest.read_text() == content:
            actions.append(("unchanged", dest))
            continue
        if dest.exists() and not force:
            actions.append(("kept", dest))
            continue
        action = "updated" if dest.exists() else "created"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        actions.append((action, dest))
    return actions


def mcp_registered() -> bool:
    try:
        config = json.loads((Path.home() / ".claude.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return MCP_NAME in (config.get("mcpServers") or {})


def mcp_add_command() -> list[str]:
    return ["claude", "mcp", "add", "-s", "user", MCP_NAME, "--", *MCP_COMMAND]


def register_mcp() -> str:
    """'unchanged', 'created', or 'missing' when the claude CLI isn't on PATH."""
    if mcp_registered():
        return "unchanged"
    claude = shutil.which("claude")
    if claude is None:
        return "missing"
    r = subprocess.run([claude, *mcp_add_command()[1:]], cwd=Path.home(), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "claude mcp add failed")
    return "created"
