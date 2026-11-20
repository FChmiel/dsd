import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export type SessionTarget =
  | { mode: "main" }
  | { mode: "existing"; worktree: string }
  | { mode: "new"; name?: string; base?: string; task?: string; task_title?: string };

export interface Worktree {
  name: string;
  path: string;
  is_main: boolean;
  branch: string | null;
  base: string | null;
  task: string | null;
  dirty?: number;
  ahead?: number | null;
  behind?: number | null;
  last_commit?: { short: string; subject: string; date: string } | null;
  terminals?: string[];
  created?: number | null;
  managed: boolean;
  origin: "main" | "dsd" | "adopted" | "current";
}

export function loadSessionDefault(): "new" | "main" {
  try { return (localStorage.getItem("dsd.session.default") as "new" | "main") || "new"; } catch { return "new"; }
}
function saveSessionDefault(v: "new" | "main") {
  try { localStorage.setItem("dsd.session.default", v); } catch { /* ignore */ }
}

/** Popover for starting an agent/shell session: new worktree (default), existing worktree, or main checkout. */
export function SessionLauncher({ pid, onStart, onClose }: {
  pid: string;
  onStart: (kind: "claude" | "shell", target: SessionTarget) => Promise<unknown>;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"new" | "existing" | "main">(loadSessionDefault());
  const [name, setName] = useState("");
  const [base, setBase] = useState("");
  const [existing, setExisting] = useState("");
  const [wts, setWts] = useState<Worktree[]>([]);
  const [branches, setBranches] = useState<{ current: string | null; branches: string[] }>({ current: null, branches: [] });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Worktree[]>(`/api/p/${pid}/worktrees`).then((w) => {
      setWts(w);
      const linked = w.filter((x) => !x.is_main);
      if (linked[0]) setExisting(linked[0].name);
    }).catch(() => setWts([]));
    api(`/api/p/${pid}/branches`).then((b) => { setBranches(b); setBase(b.current ?? ""); }).catch(() => {});
  }, [pid]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      const el = e.target as Element;
      if (!ref.current?.contains(el) && !el.closest?.("[data-launcher-toggle]")) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [onClose]);

  const linked = wts.filter((w) => !w.is_main);
  const start = async (kind: "claude" | "shell") => {
    setBusy(true);
    setErr(null);
    try {
      if (mode !== "existing") saveSessionDefault(mode);
      const target: SessionTarget =
        mode === "new" ? { mode: "new", name: name.trim() || undefined, base: base || undefined }
          : mode === "existing" ? { mode: "existing", worktree: existing } : { mode: "main" };
      await onStart(kind, target);
      onClose();
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="launcher" ref={ref} onKeyDown={(e) => { if (e.key === "Enter" && !busy) start("claude"); }}>
      <div className="launcher-title">New session</div>
      <label className={`launcher-opt ${mode === "new" ? "on" : ""}`}>
        <input type="radio" checked={mode === "new"} onChange={() => setMode("new")} />
        <div>
          <div><b>New worktree</b> <span className="muted">isolated branch for this session</span></div>
          {mode === "new" && (
            <div className="launcher-fields">
              <input className="input mono" autoFocus placeholder="name (auto)" value={name} onChange={(e) => setName(e.target.value)} />
              <select className="input" value={base} onChange={(e) => setBase(e.target.value)} title="Base branch">
                {branches.branches.map((b) => <option key={b} value={b}>from {b}</option>)}
              </select>
            </div>
          )}
          {mode === "new" && <div className="muted mono" style={{ fontSize: 11, marginTop: 4 }}>branch dsd/{name.trim() ? name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-") : "<auto>"}</div>}
        </div>
      </label>
      <label className={`launcher-opt ${mode === "existing" ? "on" : ""} ${linked.length ? "" : "disabled"}`}>
        <input type="radio" disabled={!linked.length} checked={mode === "existing"} onChange={() => setMode("existing")} />
        <div>
          <div><b>Existing worktree</b> {!linked.length && <span className="muted">none yet</span>}</div>
          {mode === "existing" && (
            <div className="launcher-fields">
              <select className="input" value={existing} onChange={(e) => setExisting(e.target.value)} style={{ flex: 1 }}>
                {linked.map((w) => (
                  <option key={w.name} value={w.name}>
                    {w.name}{w.dirty ? ` · ${w.dirty} changed` : ""}{w.ahead ? ` · ↑${w.ahead}` : ""}{w.terminals?.length ? " · open" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </label>
      <label className={`launcher-opt ${mode === "main" ? "on" : ""}`}>
        <input type="radio" checked={mode === "main"} onChange={() => setMode("main")} />
        <div><b>Main checkout</b> <span className="muted">{branches.current ? `on ${branches.current}` : ""}</span></div>
      </label>
      {err && <div className="error-box" style={{ margin: "8px 0 0", fontSize: 12 }}>{err}</div>}
      <div className="launcher-actions">
        <button className="btn primary" disabled={busy || (mode === "existing" && !existing)} onClick={() => start("claude")}>
          {busy ? "Starting…" : "Start Claude"} <span className="kbd" style={{ color: "inherit", borderColor: "rgb(255 255 255 / .4)" }}>↵</span>
        </button>
        <button className="btn" disabled={busy || (mode === "existing" && !existing)} onClick={() => start("shell")}>Shell</button>
      </div>
    </div>
  );
}
