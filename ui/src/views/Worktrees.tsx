import { useState } from "react";
import { del, fmtTime, post, tildify, useApi } from "../api";
import { useApp } from "../context";
import { href, linkProps, navigate } from "../router";
import type { Worktree } from "../components/SessionLauncher";

type Panel = { name: string; kind: "commit" | "merge" | "remove" } | null;

export function Worktrees() {
  const { project, newSession, openLauncher, terminals, toast } = useApp();
  const wts = useApi<Worktree[]>(`/api/p/${project.id}/worktrees`, { poll: 5000 });
  const [panel, setPanel] = useState<Panel>(null);
  const [adopting, setAdopting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: () => Promise<any>, ok: string) => {
    setError(null);
    try {
      await fn();
      toast(ok);
      setPanel(null);
      wts.reload();
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  const list = wts.data ?? [];
  return (
    <div className="page">
      <div className="page-head">
        <h1>Worktrees</h1>
        <span className="sub">one isolated checkout per agent session, on branch <code>dsd/&lt;name&gt;</code></span>
        <span className="spacer" />
        <button className="btn" onClick={() => setAdopting((a) => !a)}>Adopt existing worktree…</button>
        <button className="btn primary" onClick={openLauncher}>+ New session</button>
      </div>
      {error && <div className="error-box" style={{ marginBottom: 12 }}>{error}</div>}
      {adopting && <AdoptPanel pid={project.id} onAdopt={(path) => act(async () => { await post(`/api/p/${project.id}/worktrees/adopt`, { path }); setAdopting(false); }, "Worktree adopted")} onCancel={() => setAdopting(false)} />}
      {wts.data && list.length === 0 && <div className="card"><div className="empty">This project isn't a git repo.</div></div>}
      <div className="stack" style={{ gap: 10 }}>
        {list.map((w) => {
          const sessions = terminals.filter((t) => (t.worktree ?? "main") === w.name && !t.exited);
          const open = panel?.name === w.name ? panel : null;
          const target = w.is_main ? { mode: "main" as const } : { mode: "existing" as const, worktree: w.name };
          return (
            <div key={w.name} className="card wt-card">
              <div className="wt-top">
                <div className="wt-title">
                  <b>{w.is_main ? "★ main checkout" : w.name}</b>
                  <span className="mono dim" style={{ fontSize: 12 }}>{w.branch ?? "(detached)"}{w.base ? <span className="muted"> ← {w.base}</span> : null}</span>
                  {(w.origin === "adopted" || w.origin === "current") && (
                    <span className="pill" title={w.origin === "current" ? "The worktree you started dsd from. Adopt it to keep it listed." : "Created outside dsd (e.g. by Pane). dsd won't delete it unless you remove it."}>
                      {w.origin}
                    </span>
                  )}
                  {w.task && <a className="mono" style={{ fontSize: 12 }} {...linkProps(`${href(project.id, "plans")}?task=${w.task}`)}>{w.task}</a>}
                </div>
                <div className="wt-badges">
                  {!w.is_main && w.ahead != null && (
                    <span className="ab mono" style={{ fontSize: 12 }} title={`${w.ahead} commit(s) ahead of ${w.base}, ${w.behind} behind`}>
                      <span className="a">↑{w.ahead}</span> <span className="b">↓{w.behind}</span>
                    </span>
                  )}
                  {w.dirty ? <span className="pill killed">{w.dirty} uncommitted</span> : <span className="pill done">clean</span>}
                  {sessions.map((t) => <span key={t.id} className="pill running">{t.kind}</span>)}
                </div>
              </div>
              <div className="wt-meta">
                <span className="mono muted" title={w.path}>{w.path.replace(/^\/Users\/[^/]+/, "~")}</span>
                {w.last_commit && <span className="muted">· <span className="mono">{w.last_commit.short}</span> {w.last_commit.subject} · {fmtTime(w.last_commit.date)}</span>}
              </div>
              <div className="wt-actions">
                <button className="btn sm primary" onClick={() => newSession("claude", target)}>Claude here</button>
                <button className="btn sm" onClick={() => newSession("shell", target)}>Shell</button>
                <button className="btn sm" onClick={() => navigate(`${href(project.id, "changes")}${w.is_main ? "" : `?worktree=${encodeURIComponent(w.name)}`}`)}>Review changes</button>
                {!w.is_main && <>
                  <span className="spacer" />
                  {w.origin === "current" && <button className="btn sm ghost" onClick={() => act(() => post(`/api/p/${project.id}/worktrees/adopt`, { path: w.path }), `Adopted ${w.name}`)}>Adopt</button>}
                  {w.origin === "adopted" && <button className="btn sm ghost" title="Stop listing it; the directory and branch stay" onClick={() => act(() => post(`/api/p/${project.id}/worktrees/${w.name}/hide`, {}), `Hid ${w.name}`)}>Hide</button>}
                  <button className="btn sm ghost" disabled={!w.dirty} onClick={() => setPanel(open?.kind === "commit" ? null : { name: w.name, kind: "commit" })}>Commit…</button>
                  <button className="btn sm ghost" disabled={!w.ahead} title={w.ahead ? "" : "No commits to merge yet"}
                    onClick={() => setPanel(open?.kind === "merge" ? null : { name: w.name, kind: "merge" })}>Merge…</button>
                  <button className="btn sm ghost danger" onClick={() => setPanel(open?.kind === "remove" ? null : { name: w.name, kind: "remove" })}>Remove…</button>
                </>}
              </div>
              {open && (
                <div style={{ marginTop: 8 }}>
                  {open.kind === "commit" && <CommitPanel onCommit={(msg) => act(() => post(`/api/p/${project.id}/worktrees/${w.name}/commit`, { message: msg }), `Committed in ${w.name}`)} onCancel={() => setPanel(null)} task={w.task} />}
                  {open.kind === "merge" && <MergePanel w={w} onMerge={(strategy) => act(() => post(`/api/p/${project.id}/worktrees/${w.name}/merge`, { strategy }), `Merged ${w.branch} into ${w.base}`)} onCancel={() => setPanel(null)} />}
                  {open.kind === "remove" && <RemovePanel w={w} onRemove={(force, delBranch) => act(() => del(`/api/p/${project.id}/worktrees/${w.name}?force=${force}&delete_branch=${delBranch}`), `Removed ${w.name}`)} onCancel={() => setPanel(null)} />}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
        Experiment runs from any worktree land in this project's shared run history (tagged with the worktree), so leaderboards compare across branches.
        Configure a setup step and extra files to copy in <code>{tildify(project.data_dir)}/project.toml</code>: <code>[worktree] setup = "uv sync"</code>, <code>copy = [".env"]</code>.
      </p>
    </div>
  );
}

function AdoptPanel({ pid, onAdopt, onCancel }: { pid: string; onAdopt: (path: string) => void; onCancel: () => void }) {
  const cands = useApi<{ name: string; path: string; branch: string | null }[]>(`/api/p/${pid}/worktrees/candidates`);
  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div className="card-head">Other worktrees of this repo <span className="spacer" /><button className="btn sm ghost" onClick={onCancel}>Close</button></div>
      <div className="card-body stack" style={{ gap: 6 }}>
        {cands.data && cands.data.length === 0 && <div className="muted">No other worktrees.</div>}
        {cands.data?.map((c) => (
          <div key={c.path} style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <b style={{ minWidth: 140 }}>{c.name}</b>
            <span className="mono dim" style={{ fontSize: 12 }}>{c.branch ?? "(detached)"}</span>
            <span className="mono muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={c.path}>{tildify(c.path)}</span>
            <span className="spacer" />
            <button className="btn sm" onClick={() => onAdopt(c.path)}>Adopt</button>
          </div>
        ))}
      </div>
    </div>
  );
}

function CommitPanel({ onCommit, onCancel, task }: { onCommit: (m: string) => void; onCancel: () => void; task: string | null }) {
  const [msg, setMsg] = useState("");
  const full = () => (task && !/Task:/.test(msg) ? `${msg.trim()}\n\nTask: ${task}` : msg.trim());
  return (
    <div className="wt-panel">
      <input className="input" style={{ flex: 1, minWidth: 260 }} autoFocus placeholder="Commit message (stages everything in the worktree)"
        value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && msg.trim() && onCommit(full())} />
      {task && <span className="muted mono" style={{ fontSize: 11.5 }}>+ Task: {task}</span>}
      <button className="btn sm primary" disabled={!msg.trim()} onClick={() => onCommit(full())}>Commit</button>
      <button className="btn sm ghost" onClick={onCancel}>Cancel</button>
    </div>
  );
}

function MergePanel({ w, onMerge, onCancel }: { w: Worktree; onMerge: (s: "merge" | "squash") => void; onCancel: () => void }) {
  return (
    <div className="wt-panel">
      <span>Merge <code>{w.branch}</code> ({w.ahead} commit{w.ahead === 1 ? "" : "s"}) into <code>{w.base}</code> in the main checkout?</span>
      {w.dirty ? <span className="pill killed">commit the {w.dirty} uncommitted change(s) first</span> : null}
      <span className="spacer" />
      <button className="btn sm primary" disabled={!!w.dirty} onClick={() => onMerge("merge")}>Merge commit</button>
      <button className="btn sm" disabled={!!w.dirty} onClick={() => onMerge("squash")}>Squash</button>
      <button className="btn sm ghost" onClick={onCancel}>Cancel</button>
    </div>
  );
}

function RemovePanel({ w, onRemove, onCancel }: { w: Worktree; onRemove: (force: boolean, delBranch: boolean) => void; onCancel: () => void }) {
  const [delBranch, setDelBranch] = useState(false);
  const [force, setForce] = useState(false);
  return (
    <div className="wt-panel">
      <span>Remove worktree <b>{w.name}</b>? Its terminals will close.{w.origin !== "dsd" ? " dsd didn't create it; use Hide to just stop listing it." : ""}</span>
      {w.dirty ? (
        <label className="dim" style={{ display: "flex", gap: 5, alignItems: "center" }}>
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          discard {w.dirty} uncommitted change{w.dirty === 1 ? "" : "s"}
        </label>
      ) : null}
      <label className="dim" style={{ display: "flex", gap: 5, alignItems: "center" }}>
        <input type="checkbox" checked={delBranch} onChange={(e) => setDelBranch(e.target.checked)} />
        also delete branch {w.branch}{w.ahead ? ` (${w.ahead} unmerged commit${w.ahead === 1 ? "" : "s"})` : ""}
      </label>
      <span className="spacer" />
      <button className="btn sm danger" disabled={!!w.dirty && !force} onClick={() => onRemove(force, delBranch)}>Remove</button>
      <button className="btn sm ghost" onClick={onCancel}>Cancel</button>
    </div>
  );
}
