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
import sys
from importlib.resources import files
from pathlib import Path

MANAGED_FILE = ".dsd-managed"
MCP_NAME = "dsd"


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


def dsd_executable() -> str:
    """The dsd command for Claude Code to run: the app's stable shim, or this environment's own `dsd` script."""
    from .appsupport import ensure_app_shim, frozen_executable

    if frozen_executable() is not None:
        shim = ensure_app_shim()
        return str(shim / "dsd") if shim else str(frozen_executable())
    script = Path(sys.prefix) / "bin" / "dsd"
    if script.exists():
        return str(script)
    return shutil.which("dsd") or "dsd"


def mcp_command() -> list[str]:
    return [dsd_executable(), "mcp"]


def registered_mcp() -> dict | None:
    try:
        config = json.loads((Path.home() / ".claude.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return (config.get("mcpServers") or {}).get(MCP_NAME)


def mcp_status() -> dict:
    """connected, missing, or stale (registered, but runs a different or missing dsd)."""
    entry = registered_mcp()
    expected = mcp_command()
    if entry is None:
        state = "missing"
        command = None
    else:
        command = [entry.get("command", ""), *entry.get("args", [])]
        exe = command[0]
        runnable = Path(exe).exists() if "/" in exe else shutil.which(exe) is not None
        state = "connected" if command == expected and runnable else "stale"
    return {"state": state, "command": command, "expected": expected, "claude_cli": shutil.which("claude") is not None}


def mcp_add_command() -> list[str]:
    return ["claude", "mcp", "add", "-s", "user", MCP_NAME, "--", *mcp_command()]


def register_mcp() -> str:
    """'unchanged', 'created', 'updated', or 'missing' when the claude CLI isn't on PATH."""
    status = mcp_status()
    if status["state"] == "connected":
        return "unchanged"
    claude = shutil.which("claude")
    if claude is None:
        return "missing"
    if status["state"] == "stale":
        subprocess.run([claude, "mcp", "remove", "-s", "user", MCP_NAME], cwd=Path.home(), capture_output=True, text=True)
    r = subprocess.run([claude, *mcp_add_command()[1:]], cwd=Path.home(), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "claude mcp add failed")
    return "updated" if status["state"] == "stale" else "created"


def refresh_installed_skills() -> list[tuple[str, Path]]:
    """At startup: if the user has installed dsd's skills before, add new ones and update unedited ones."""
    bundled = bundled_skills()
    if all(skill_state(n, b) == "missing" for n, b in bundled.items()):
        return []
    return [(a, p) for a, p in install_skills(force=False) if a != "unchanged"]


def session_mcp_config() -> Path:
    """A one-session MCP config that runs this dsd (for `claude --mcp-config`), kept in ~/.dsd/claude/."""
    from .project import dsd_home

    path = dsd_home() / "claude" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {"mcpServers": {MCP_NAME: {"type": "stdio", "command": dsd_executable(), "args": ["mcp"]}}}
    text = json.dumps(config, indent=2) + "\n"
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


def claude_session_command(claude: str) -> str:
    """The command the dsd app types to start Claude: dsd's skills installed or updated (edits kept), and the dsd
    MCP server passed for this session when the user's own registration is missing or points elsewhere."""
    import shlex

    install_skills(force=False)
    if mcp_status()["state"] == "connected":
        return claude
    return f"{claude} --mcp-config {shlex.quote(str(session_mcp_config()))}"
