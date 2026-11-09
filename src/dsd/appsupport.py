"""Support for the packaged desktop app (frozen backend): CLI shims so Claude Code can run `dsd mcp`."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import registry


def frozen_executable() -> Path | None:
    """The bundled dsd binary when running inside the app (PyInstaller), else None."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def _link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        if link.is_symlink() and Path(os.readlink(link)) == target:
            return
        link.unlink()
    link.symlink_to(target)


def ensure_app_shim() -> Path | None:
    """~/.dsd/bin/dsd -> the bundled binary. Terminals started by the app put this dir first on PATH."""
    exe = frozen_executable()
    if exe is None:
        return None
    d = registry.home() / "bin"
    try:
        _link(d / "dsd", exe)
    except OSError:
        return None
    return d


def login_shell_lookup() -> tuple[str | None, list[str]]:
    """(path of `dsd` on the user's login-shell PATH, that PATH) - what a Terminal.app session would see."""
    shell = os.environ.get("SHELL", "/bin/zsh")
    try:
        out = subprocess.run([shell, "-l", "-i", "-c", 'command -v dsd; printf "\\n%s" "$PATH"'],
                             capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, []
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    path_line = lines[-1] if lines else ""
    found = lines[0] if len(lines) > 1 and lines[0].startswith("/") else None
    return found, path_line.split(":")


def cli_status() -> dict:
    exe = frozen_executable()
    found, path = login_shell_lookup()
    target = None
    if found:
        try:
            target = str(Path(found).resolve())
        except OSError:
            target = found
    return {
        "frozen": exe is not None,
        "executable": str(exe) if exe else sys.executable,
        "on_path": found,
        "points_to_app": bool(exe and target == str(exe)),
    }


def install_cli() -> dict:
    """Link ~/.local/bin/dsd to the bundled binary (like VS Code's 'Install code command')."""
    exe = frozen_executable()
    if exe is None:
        raise RuntimeError("Not running from the packaged app; install with `uv tool install` instead")
    link = Path.home() / ".local" / "bin" / "dsd"
    _link(link, exe)
    _, path = login_shell_lookup()
    on_path = str(link.parent) in path
    return {
        "linked": str(link),
        "on_path": on_path,
        "hint": None if on_path else 'Add ~/.local/bin to your PATH, e.g. echo \'export PATH="$HOME/.local/bin:$PATH"\' >> ~/.zshrc',
    }
