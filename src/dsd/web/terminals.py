"""PTY-backed terminal sessions for the app's agent pane.

Sessions live as long as the dsd server: the browser can disconnect and reattach (scrollback is
replayed). Each session runs the user's login shell in the project root; "claude" sessions start
the shell and then type `claude`, so you land back in the shell when Claude exits.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import shlex
import signal
import struct
import subprocess
import termios
import time
from dataclasses import dataclass, field

from ..ids import ulid

SCROLLBACK = 256 * 1024
HIGH_WATER = 1_000_000
LOW_WATER = 250_000
MAX_FRAME = 256 * 1024
FRAME_DELAY = 0.006
_claude_cmd: str | None = None


CLAUDE_SESSION_MARKERS = (
    "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDE_EFFORT",
)


def _claude_startup() -> str:
    claude = resolve_claude_command()
    if claude.startswith("echo "):
        return claude
    from ..agents import claude_session_command

    try:
        return claude_session_command(claude)
    except OSError:
        return claude


def resolve_claude_command() -> str:
    """How to launch Claude Code: $DSD_CLAUDE_CMD, `claude` on the login-shell PATH,
    common install locations, then the newest binary bundled with the VS Code extension."""
    global _claude_cmd
    if os.environ.get("DSD_CLAUDE_CMD"):
        return os.environ["DSD_CLAUDE_CMD"]
    if _claude_cmd is not None:
        return _claude_cmd
    from ..agents import installed_claude, login_shell_claude

    if login_shell_claude():
        _claude_cmd = "claude"
        return _claude_cmd
    installed = installed_claude()
    if installed:
        _claude_cmd = shlex.quote(str(installed))
        return _claude_cmd
    _claude_cmd = ("echo 'dsd: Claude Code CLI not found. Install it (npm i -g @anthropic-ai/claude-code)"
                   " or set DSD_CLAUDE_CMD.'")
    return _claude_cmd


class Listener:
    """One browser connection: its outgoing queue and, once it acknowledges output, how much is unacknowledged."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.flow = False
        self.unacked = 0


@dataclass
class Terminal:
    id: str
    project_id: str
    title: str
    kind: str  # "claude" | "shell" | "cmd"
    cwd: str
    proc: subprocess.Popen
    fd: int
    created: float = field(default_factory=time.time)
    buffer: bytearray = field(default_factory=bytearray)
    listeners: set = field(default_factory=set)
    exited: bool = False
    paused: bool = False
    worktree: str | None = None  # None = main checkout
    branch: str | None = None

    def info(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "title": self.title, "kind": self.kind,
                "cwd": self.cwd, "created": self.created, "exited": self.exited, "pid": self.proc.pid,
                "worktree": self.worktree, "branch": self.branch}


class TerminalManager:
    def __init__(self):
        self.terms: dict[str, Terminal] = {}

    def list(self, project_id: str | None = None) -> list[dict]:
        return [t.info() for t in self.terms.values() if project_id is None or t.project_id == project_id]

    def create(self, project_id: str, cwd: str, kind: str = "shell", title: str | None = None,
               command: str | None = None, env: dict | None = None, worktree: str | None = None,
               branch: str | None = None, setup: str | None = None) -> Terminal:
        shell = os.environ.get("SHELL", "/bin/zsh")
        master, slave = pty.openpty()
        _set_size(master, 32, 120)
        full_env = {**os.environ, **(env or {}), "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        for key in ("DSD_RUN_DIR", "DSD_PROJECT_ROOT", *CLAUDE_SESSION_MARKERS):
            full_env.pop(key, None)
        from ..appsupport import ensure_app_shim

        shim_dir = ensure_app_shim()  # packaged app: make `dsd` (and so `dsd mcp`) resolvable in the session
        if shim_dir:
            full_env["PATH"] = f"{shim_dir}:{full_env.get('PATH', '/usr/bin:/bin')}"
        if worktree:  # informational; dsd finds the worktree's project from the cwd
            full_env["DSD_WORKTREE"] = worktree
        proc = subprocess.Popen(
            [shell, "-l", "-i"], cwd=cwd, env=full_env, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, close_fds=True, preexec_fn=_take_controlling_tty,
        )
        os.close(slave)
        os.set_blocking(master, False)
        tid = ulid()
        default_title = ("Claude" if kind == "claude" else "Shell") + (f" · {worktree}" if worktree else "")
        term = Terminal(tid, project_id, title or default_title, kind, cwd, proc, master, worktree=worktree, branch=branch)
        self.terms[tid] = term
        loop = asyncio.get_running_loop()
        loop.add_reader(master, self._on_readable, term)
        startup = command or (_claude_startup() if kind == "claude" else None)
        if setup:  # e.g. `uv sync` in a fresh worktree, then start the agent
            startup = f"{setup} && {startup}" if startup else setup
        if startup:
            loop.call_later(0.4, self.write, tid, (startup + "\r").encode())
        return term

    def _on_readable(self, term: Terminal) -> None:
        chunks: list[bytes] = []
        size, ended = 0, False
        while size < MAX_FRAME:
            try:
                piece = os.read(term.fd, 65536)
            except BlockingIOError:
                break
            except OSError:
                piece = b""
            if not piece:
                ended = True
                break
            chunks.append(piece)
            size += len(piece)
        if not chunks:
            if ended:
                self._mark_exited(term)
            return
        data = b"".join(chunks)
        term.buffer.extend(data)
        if len(term.buffer) > SCROLLBACK:
            del term.buffer[: len(term.buffer) - SCROLLBACK]
        for listener in list(term.listeners):
            listener.queue.put_nowait(data)
            if listener.flow:
                listener.unacked += len(data)
        if not term.paused and any(lst.flow and lst.unacked > HIGH_WATER for lst in term.listeners):
            asyncio.get_running_loop().remove_reader(term.fd)
            term.paused = True
        if ended:
            self._mark_exited(term)

    def ack(self, term: Terminal, listener: Listener, n: int) -> None:
        listener.unacked = max(0, listener.unacked - n)
        self._resume_if_drained(term)

    def detach(self, term: Terminal, listener: Listener) -> None:
        term.listeners.discard(listener)
        self._resume_if_drained(term)

    def _resume_if_drained(self, term: Terminal) -> None:
        if term.paused and not term.exited and all(not lst.flow or lst.unacked < LOW_WATER for lst in term.listeners):
            term.paused = False
            asyncio.get_running_loop().add_reader(term.fd, self._on_readable, term)

    def _mark_exited(self, term: Terminal) -> None:
        if term.exited:
            return
        term.exited = True
        try:
            asyncio.get_running_loop().remove_reader(term.fd)
        except Exception:
            pass
        msg = b"\r\n\x1b[2m[process exited]\x1b[0m\r\n"
        term.buffer.extend(msg)
        for listener in list(term.listeners):
            listener.queue.put_nowait(msg)
            listener.queue.put_nowait(None)

    def write(self, tid: str, data: bytes) -> None:
        term = self.terms.get(tid)
        if term is None or term.exited:
            return
        view = memoryview(data)
        while view:
            try:
                n = os.write(term.fd, view)
                view = view[n:]
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                return

    def paste(self, tid: str, text: str, submit: bool = False) -> None:
        """Bracketed paste so multi-line text isn't submitted line by line."""
        payload = b"\x1b[200~" + text.encode() + b"\x1b[201~"
        if submit:
            payload += b"\r"
        self.write(tid, payload)

    def resize(self, tid: str, rows: int, cols: int) -> None:
        term = self.terms.get(tid)
        if term and not term.exited:
            _set_size(term.fd, rows, cols)
            try:
                pgrp = os.tcgetpgrp(term.fd)
            except OSError:
                pgrp = os.getpgid(term.proc.pid)
            try:
                os.killpg(pgrp, signal.SIGWINCH)
            except OSError:
                pass

    def rename(self, tid: str, title: str) -> None:
        if tid in self.terms:
            self.terms[tid].title = title

    def close(self, tid: str) -> None:
        term = self.terms.pop(tid, None)
        if term is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(term.fd)
        except Exception:
            pass
        try:
            os.killpg(os.getpgid(term.proc.pid), signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(term.fd)
        except OSError:
            pass

    def close_all(self) -> None:
        for tid in list(self.terms):
            self.close(tid)


def _take_controlling_tty() -> None:
    """Runs in the child after setsid: make the PTY its controlling terminal, so the kernel tells the
    foreground job (e.g. claude, which zsh runs in its own process group) about window size changes."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _set_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
