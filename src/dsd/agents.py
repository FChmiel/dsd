"""`dsd setup`: wire dsd into Claude Code for the user, outside any repo.

Registers the dsd MCP server in user scope (`claude mcp add -s user dsd -- dsd mcp`) and installs the
dsd skills into ~/.claude/skills. Idempotent. Each installed skill gets a .dsd-managed file with the
hashes of what was installed, so a later setup updates skills the user hasn't edited and keeps the rest.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

MANAGED_FILE = ".dsd-managed"
MCP_NAME = "dsd"
MCP_COMMAND = ["dsd", "mcp"]


def claude_dir() -> Path:
    return Path.home() / ".claude"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk(node, prefix: str = ""):
    for child in sorted(node.iterdir(), key=lambda c: c.name):
        if child.is_dir():
            yield from _walk(child, f"{prefix}{child.name}/")
        else:
            yield f"{prefix}{child.name}", child.read_bytes()


def bundled_skills() -> dict[str, dict[str, bytes]]:
    src = files("dsd.templates").joinpath("skills")
    return {s.name: dict(_walk(s)) for s in sorted(src.iterdir(), key=lambda s: s.name) if s.is_dir()}


def _installed(dest: Path) -> dict[str, str] | None:
    try:
        return json.loads((dest / MANAGED_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def skill_state(name: str, bundled: dict[str, bytes]) -> str:
    """missing, current, outdated (safe to update) or edited (the user changed it since it was installed)."""
    dest = claude_dir() / "skills" / name
    if not dest.exists():
        return "missing"
    on_disk = {rel: _sha((dest / rel).read_bytes()) for rel in bundled if (dest / rel).is_file()}
    if on_disk == {rel: _sha(data) for rel, data in bundled.items()}:
        return "current"
    manifest = _installed(dest)
    if manifest is not None and all(on_disk.get(rel) == h for rel, h in manifest.items()):
        return "outdated"
    return "edited"


def install_skills(force: bool = False) -> list[tuple[str, Path]]:
    actions = []
    for name, bundled in bundled_skills().items():
        dest = claude_dir() / "skills" / name
        state = skill_state(name, bundled)
        if state == "edited" and not force:
            actions.append(("kept", dest))
            continue
        for rel, data in bundled.items() if state != "current" else ():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(data)
        manifest = json.dumps({rel: _sha(data) for rel, data in bundled.items()}, indent=1)
        if (_installed(dest) or {}) != json.loads(manifest):
            (dest / MANAGED_FILE).write_text(manifest + "\n")
        actions.append(({"missing": "created", "current": "unchanged"}.get(state, "updated"), dest))
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
