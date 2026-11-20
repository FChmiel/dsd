import { useEffect, useRef, useState } from "react";
import { SessionLauncher, type SessionTarget } from "./SessionLauncher";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";

export interface TermInfo {
  id: string;
  title: string;
  kind: string;
  exited: boolean;
  worktree?: string | null;
  branch?: string | null;
}

const THEME = {
  background: "#0d0d0c",
  foreground: "#e6e5e0",
  cursor: "#e6e5e0",
  cursorAccent: "#0d0d0c",
  selectionBackground: "#3a4a63",
  black: "#1f1f1e", red: "#f0605d", green: "#4ac26b", yellow: "#d29922", blue: "#3987e5",
  magenta: "#c678dd", cyan: "#3fb6c6", white: "#d4d3cd",
  brightBlack: "#6b6a65", brightRed: "#ff7b78", brightGreen: "#7ee2a0", brightYellow: "#f0c05a",
  brightBlue: "#86b6ef", brightMagenta: "#e0a3f0", brightCyan: "#7fd8e4", brightWhite: "#ffffff",
};

function wsUrl(tid: string) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/terminals/${tid}/ws`;
}

/** One xterm bound to one server-side PTY. Stays mounted while hidden so state survives tab switches. */
export function TerminalView({ tid, active, onExit }: { tid: string; active: boolean; onExit: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const term = new Terminal({
      theme: THEME,
      fontFamily: '"JetBrains Mono", "SF Mono", Menlo, monospace',
      fontSize: 12.5,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 10000,
      allowProposedApi: true,
      macOptionIsMeta: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(host.current!);
    termRef.current = term;
    fitRef.current = fit;

    let disposed = false;
    let retry: number | undefined;
    const enc = new TextEncoder();

    const sendResize = () => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
    };

    const connect = (attempt = 0) => {
      const ws = new WebSocket(wsUrl(tid));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      let first = true;
      ws.onopen = () => {
        try { fit.fit(); } catch { /* hidden */ }
        sendResize();
      };
      ws.onmessage = (ev) => {
        if (first) {
          term.reset();
          first = false;
        }
        term.write(typeof ev.data === "string" ? ev.data : new Uint8Array(ev.data));
      };
      ws.onclose = (ev) => {
        if (disposed) return;
        if (ev.code === 4404) {
          onExit();
          return;
        }
        // server restarted or connection dropped: retry with backoff
        if (attempt < 20) retry = window.setTimeout(() => connect(attempt + 1), Math.min(500 * 2 ** attempt, 5000));
      };
    };
    connect();

    const dataSub = term.onData((d) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(enc.encode(d));
    });
    term.attachCustomKeyEventHandler((e) => {
      if (e.key !== "Enter" || !e.shiftKey || e.metaKey || e.ctrlKey || e.altKey) return true;
      if (e.type === "keydown") {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(enc.encode("\x1b\r"));
      }
      return false;
    });
    const resizeSub = term.onResize(sendResize);
    let refit: number | undefined;
    const ro = new ResizeObserver(() => {
      window.clearTimeout(refit);
      refit = window.setTimeout(() => {
        if (host.current && host.current.offsetWidth > 0) {
          try { fit.fit(); } catch { /* ignore */ }
        }
      }, 120);
    });
    ro.observe(host.current!);

    return () => {
      disposed = true;
      window.clearTimeout(retry);
      window.clearTimeout(refit);
      ro.disconnect();
      dataSub.dispose();
      resizeSub.dispose();
      wsRef.current?.close();
      term.dispose();
    };
  }, [tid]);

  useEffect(() => {
    if (active) {
      requestAnimationFrame(() => {
        try { fitRef.current?.fit(); } catch { /* ignore */ }
        termRef.current?.focus();
      });
    }
  }, [active]);

  return <div className="term-host" ref={host} style={{ visibility: active ? "visible" : "hidden" }} />;
}

export function TerminalPane(props: {
  pid: string;
  terminals: TermInfo[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: (kind: "claude" | "shell", target: SessionTarget) => Promise<unknown>;
  onTerminal: () => void;
  terminalWhere: string;
  launcherOpen: boolean;
  setLauncherOpen: (b: boolean) => void;
  onClose: (id: string) => void;
  onRenameWorktree?: (worktree: string) => void;
  onExited: (id: string) => void;
  onHide: () => void;
  full: boolean;
  onToggleFull: () => void;
  context: string;
}) {
  const { terminals, activeId, launcherOpen, setLauncherOpen } = props;
  return (
    <div className="term-pane" style={{ position: "relative" }}>
      <div className="term-tabs">
        {props.full && <span className="term-context" title="Exit full screen to see the project">{props.context}</span>}
        {terminals.map((t) => (
          <button key={t.id} className={`term-tab ${t.id === activeId ? "active" : ""}`} onClick={() => props.onSelect(t.id)}
            onDoubleClick={() => t.worktree && props.onRenameWorktree?.(t.worktree)}
            title={`${t.kind === "claude" ? "Claude Code" : "Shell"} · ${t.worktree ? `worktree ${t.worktree}` : "main checkout"}${t.branch ? ` · ${t.branch}` : ""}${t.worktree ? " · double-click to rename" : ""}`}>
            <span className={`dot ${t.kind === "claude" ? "" : "shell"} ${t.exited ? "exited" : ""}`} />
            {t.kind === "claude" ? "Claude" : "Shell"}
            <span className="branch">{t.worktree ?? t.branch ?? "main"}</span>
            <span className="x" onClick={(e) => { e.stopPropagation(); props.onClose(t.id); }}>×</span>
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button className="term-btn" onClick={props.onTerminal} title={`Open a shell in ${props.terminalWhere}`}>+ Terminal</button>
        <button className="term-btn" data-launcher-toggle onClick={() => setLauncherOpen(!launcherOpen)} title="New Claude or shell session (new worktree, existing worktree, or main checkout)">+ New session</button>
        <button className="term-btn" onClick={props.onToggleFull} title={props.full ? "Exit full screen (⌘⇧↵)" : "Full screen (⌘⇧↵)"}>
          {props.full ? "⤡ Exit full screen" : "⤢"}
        </button>
        <button className="term-btn" onClick={props.onHide} title="Hide agent pane (⌘J)">⇥</button>
      </div>
      {launcherOpen && <SessionLauncher pid={props.pid} onStart={props.onNew} onClose={() => setLauncherOpen(false)} />}
      <div className="term-body">
        {terminals.length === 0 && (
          <div className="term-empty">
            <div className="big">Agent pane</div>
            Start <b>Claude Code</b> in this project. Once you've run <code>dsd setup</code>, it has the dsd MCP server and
            skills (<code>/dsd-plan</code>, <code>/dsd-develop</code>, <code>/dsd-review</code>, <code>/dsd-benchmark</code>…).
            <div style={{ marginTop: 6 }}>Each new session gets its <b>own git worktree</b> by default, so parallel agents never edit the same checkout.</div>
            <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
              <button className="term-btn" onClick={() => setLauncherOpen(true)}>New session…</button>
              <button className="term-btn" onClick={() => props.onNew("claude", { mode: "main" })}>Claude on main checkout</button>
              <button className="term-btn" onClick={props.onTerminal}>Terminal</button>
            </div>
          </div>
        )}
        {terminals.map((t) => (
          <TerminalView key={t.id} tid={t.id} active={t.id === activeId} onExit={() => props.onExited(t.id)} />
        ))}
      </div>
    </div>
  );
}
