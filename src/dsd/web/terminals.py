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
import signal
import struct
import subprocess
import termios
import time
from dataclasses import dataclass, field

from ..ids import ulid

SCROLLBACK = 256 * 1024


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

    def info(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "title": self.title, "kind": self.kind,
                "cwd": self.cwd, "created": self.created, "exited": self.exited, "pid": self.proc.pid}


class TerminalManager:
    def __init__(self):
        self.terms: dict[str, Terminal] = {}

    def list(self, project_id: str | None = None) -> list[dict]:
        return [t.info() for t in self.terms.values() if project_id is None or t.project_id == project_id]

    def create(self, project_id: str, cwd: str, kind: str = "shell", title: str | None = None,
               command: str | None = None, env: dict | None = None) -> Terminal:
        shell = os.environ.get("SHELL", "/bin/zsh")
        master, slave = pty.openpty()
        _set_size(master, 32, 120)
        full_env = {**os.environ, **(env or {}), "TERM": "xterm-256color", "COLORTERM": "truecolor",
                    "DSD_PROJECT_ROOT": cwd}
        full_env.pop("DSD_RUN_DIR", None)
        proc = subprocess.Popen(
            [shell, "-l", "-i"], cwd=cwd, env=full_env, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, close_fds=True,
        )
        os.close(slave)
        os.set_blocking(master, False)
        tid = ulid()
        term = Terminal(tid, project_id, title or ("Claude" if kind == "claude" else "Shell"), kind, cwd, proc, master)
        self.terms[tid] = term
        loop = asyncio.get_running_loop()
        loop.add_reader(master, self._on_readable, term)
        startup = command or ("claude" if kind == "claude" else None)
        if startup:
            loop.call_later(0.4, self.write, tid, (startup + "\r").encode())
        return term

    def _on_readable(self, term: Terminal) -> None:
        try:
            data = os.read(term.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._mark_exited(term)
            return
        term.buffer.extend(data)
        if len(term.buffer) > SCROLLBACK:
            del term.buffer[: len(term.buffer) - SCROLLBACK]
        for q in list(term.listeners):
            q.put_nowait(data)

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
        for q in list(term.listeners):
            q.put_nowait(msg)
            q.put_nowait(None)

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
                os.killpg(os.getpgid(term.proc.pid), signal.SIGWINCH)
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


def _set_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
