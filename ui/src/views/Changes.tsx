import { Fragment, useEffect, useRef, useState } from "react";
import { del, patch, post, qs, useApi } from "../api";
import { useApp } from "../context";
import { href, navigate, useRoute } from "../router";

interface DLine { t: "add" | "del" | "ctx"; old: number | null; new: number | null; text: string }
interface DFile { path: string; status: string; binary: boolean; truncated: boolean; additions: number; deletions: number; hunks: { header: string; lines: DLine[] }[] }
interface Comment { id: string; path: string; line: number | null; side: string; text: string; code: string | null; ref: string | null; worktree?: string | null; status: string }

export function Changes() {
  const { project, terminals, activeTerminal, toast } = useApp();
  const route = useRoute();
  const ref = route.query.get("ref");
  const wt = route.query.get("worktree");
  const changes = useApi<{ repo: boolean; files: DFile[]; subject?: string; branch?: string; base?: string }>(
    `/api/p/${project.id}/changes${qs({ ref, worktree: wt })}`, { poll: ref ? 0 : 4000 });
  const wts = useApi<any[]>(`/api/p/${project.id}/worktrees`, { poll: 10000 });
  const commits = useApi<any[]>(`/api/p/${project.id}/commits`, { poll: 15000 });
  const comments = useApi<Comment[]>(`/api/p/${project.id}/comments`, { poll: 4000 });
  const [draft, setDraft] = useState<{ path: string; line: number | null; side: string; code: string } | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [submit, setSubmit] = useState(false);
  const [target, setTarget] = useState<string>("");
  const fileRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    // default the target to a session running in the checkout under review (Claude first)
    const here = terminals.filter((t) => !t.exited && (t.worktree ?? null) === (ref ? null : wt ?? null));
    const pick = here.find((t) => t.kind === "claude") ?? here[0] ?? terminals.find((t) => t.kind === "claude") ?? terminals[0];
    setTarget((cur) => (cur && here.some((t) => t.id === cur) ? cur : pick?.id ?? ""));
  }, [terminals, wt, ref]);

  const files = changes.data?.files ?? [];
  const allComments = (comments.data ?? []).filter((c) => (c.worktree ?? null) === (ref ? null : wt ?? null));
  const open = allComments.filter((c) => c.status === "open");
  const visibleComments = allComments.filter((c) => showResolved || c.status !== "resolved");

  const saveComment = async (text: string) => {
    if (!draft || !text.trim()) return;
    await post(`/api/p/${project.id}/comments`, { ...draft, text, ref, worktree: ref ? null : wt });
    setDraft(null);
    comments.reload();
  };

  const send = async () => {
    if (!target) { toast("Open a Claude terminal in the agent pane first"); return; }
    const r = await post<{ sent: number }>(`/api/p/${project.id}/comments/send`, { terminal_id: target, submit, ids: open.map((c) => c.id) });
    toast(`Sent ${r.sent} comment${r.sent > 1 ? "s" : ""} to ${terminals.find((t) => t.id === target)?.title ?? "agent"}${submit ? "" : " — press Enter there to submit"}`);
    comments.reload();
  };

  return (
    <div className="page full">
      <div className="split">
        <div className="pane-l">
          <div style={{ padding: "10px 10px 6px" }}>
            <select className="input" style={{ width: "100%" }} value={ref ? `ref:${ref}` : wt ? `wt:${wt}` : ""}
              onChange={(e) => {
                const v = e.target.value;
                navigate(`${href(project.id, "changes")}${v.startsWith("ref:") ? `?ref=${v.slice(4)}` : v.startsWith("wt:") ? `?worktree=${encodeURIComponent(v.slice(3))}` : ""}`);
              }}>
              <option value="">Main checkout (uncommitted)</option>
              {(wts.data ?? []).filter((w) => !w.is_main).length > 0 && (
                <optgroup label="Worktrees (all changes vs base)">
                  {(wts.data ?? []).filter((w) => !w.is_main).map((w) => (
                    <option key={w.name} value={`wt:${w.name}`}>⎇ {w.name}{w.ahead ? ` ↑${w.ahead}` : ""}{w.dirty ? ` · ${w.dirty} changed` : ""}</option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Commits on main">
                {(commits.data ?? []).map((c) => <option key={c.sha} value={`ref:${c.short}`}>{c.short} · {c.subject.slice(0, 50)}</option>)}
              </optgroup>
            </select>
          </div>
          <div className="tree file-list">
            {files.length === 0 && <div className="empty">{changes.data?.repo === false ? "Not a git repo" : ref ? "No changes" : "Working tree clean"}</div>}
            {files.map((f) => {
              const n = allComments.filter((c) => c.path === f.path && c.status !== "resolved").length;
              return (
                <button key={f.path} className="tree-item" onClick={() => fileRefs.current[f.path]?.scrollIntoView({ behavior: "smooth", block: "start" })} title={f.path}>
                  <span className={`st ${f.status}`}>{f.status[0].toUpperCase()}</span>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{f.path}</span>
                  <span className="spacer" />
                  {n > 0 && <span className="pill running" style={{ padding: "0 5px" }}>{n}</span>}
                  <span className="diff-stat mono" style={{ fontSize: 10.5 }}><span className="a">+{f.additions}</span> <span className="d">−{f.deletions}</span></span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="pane-r">
          <div className="doc-head">
            <b>{ref ? `Commit ${ref}` : wt ? `⎇ ${wt}` : "Uncommitted changes"}</b>
            {wt && changes.data?.branch && <span className="muted mono" style={{ fontSize: 12 }}>{changes.data.branch} vs {changes.data.base}</span>}
            {changes.data?.subject && <span className="muted">{changes.data.subject.replace(/^\S+\s/, "")}</span>}
            <span className="muted">{files.length} file{files.length === 1 ? "" : "s"}</span>
            <span className="spacer" />
            <label className="muted" style={{ display: "flex", gap: 5, alignItems: "center", fontSize: 12 }}>
              <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> resolved
            </label>
            <span className="pill running">{open.length} open</span>
            <select className="input" value={target} onChange={(e) => setTarget(e.target.value)} style={{ maxWidth: 160 }}>
              {terminals.length === 0 && <option value="">no terminal open</option>}
              {terminals.map((t) => <option key={t.id} value={t.id}>{t.kind === "claude" ? "Claude" : "Shell"} · {t.worktree ?? "main"}</option>)}
            </select>
            <label className="muted" style={{ display: "flex", gap: 5, alignItems: "center", fontSize: 12 }} title="Press Enter in the terminal automatically">
              <input type="checkbox" checked={submit} onChange={(e) => setSubmit(e.target.checked)} /> submit
            </label>
            <button className="btn primary sm" disabled={open.length === 0} onClick={send}>Send to agent</button>
          </div>
          <div style={{ padding: "14px 18px" }}>
            {changes.error && <div className="error-box">{changes.error}</div>}
            {visibleComments.filter((c) => !files.some((f) => f.path === c.path)).length > 0 && (
              <div className="card" style={{ marginBottom: 14 }}>
                <div className="card-head">Comments on files not in this view</div>
                <div className="card-body stack" style={{ gap: 6 }}>
                  {visibleComments.filter((c) => !files.some((f) => f.path === c.path)).map((c) => (
                    <CommentCard key={c.id} c={c} reload={comments.reload} showLoc />
                  ))}
                </div>
              </div>
            )}
            {files.map((f) => (
              <div key={f.path} className="diff-file" ref={(el) => (fileRefs.current[f.path] = el)}>
                <div className="diff-file-head">
                  <span className={`st ${f.status}`}>{f.status}</span>
                  <b>{f.path}</b>
                  <span className="spacer" />
                  <span className="diff-stat"><span className="a">+{f.additions}</span> <span className="d">−{f.deletions}</span></span>
                  <button className="btn sm ghost" onClick={() => setDraft({ path: f.path, line: null, side: "new", code: "" })}>Comment on file</button>
                </div>
                {draft && draft.path === f.path && draft.line === null && <CommentEditor onSave={saveComment} onCancel={() => setDraft(null)} />}
                {visibleComments.filter((c) => c.path === f.path && c.line === null).map((c) => (
                  <div key={c.id} className="comment-box" style={{ marginLeft: 10 }}><CommentCard c={c} reload={comments.reload} /></div>
                ))}
                {f.binary ? <div className="empty">Binary file</div> : (
                  <table className="diff">
                    <tbody>
                      {f.hunks.map((h, hi) => (
                        <Fragment key={hi}>
                          <tr className="hunk"><td colSpan={4}>{h.header}</td></tr>
                          {h.lines.map((ln, li) => {
                            const line = ln.new ?? ln.old;
                            const side = ln.t === "del" ? "old" : "new";
                            const lineComments = visibleComments.filter((c) => c.path === f.path && c.line === line && c.side === side);
                            return (
                              <Fragment key={li}>
                                <tr className={`line ${ln.t}`}>
                                  <td className="ln">{ln.old ?? ""}</td>
                                  <td className="ln">{ln.new ?? ""}</td>
                                  <td className="gutter">
                                    <button className="add-comment" title="Comment on this line"
                                      onClick={() => setDraft({ path: f.path, line, side, code: ln.text })}>+</button>
                                  </td>
                                  <td className="code">{ln.t === "add" ? "+" : ln.t === "del" ? "−" : " "}{ln.text}</td>
                                </tr>
                                {(lineComments.length > 0 || (draft && draft.path === f.path && draft.line === line && draft.side === side)) && (
                                  <tr><td colSpan={4} style={{ padding: 0 }}>
                                    <div className="comment-box stack" style={{ gap: 6 }}>
                                      {lineComments.map((c) => <CommentCard key={c.id} c={c} reload={comments.reload} />)}
                                      {draft && draft.path === f.path && draft.line === line && draft.side === side && (
                                        <CommentEditor onSave={saveComment} onCancel={() => setDraft(null)} />
                                      )}
                                    </div>
                                  </td></tr>
                                )}
                              </Fragment>
                            );
                          })}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                )}
                {f.truncated && <div className="empty">Diff truncated</div>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CommentEditor({ onSave, onCancel }: { onSave: (t: string) => void; onCancel: () => void }) {
  const [text, setText] = useState("");
  return (
    <div className="comment-box" style={{ margin: "6px 10px 8px" }}>
      <textarea className="input" autoFocus rows={2} style={{ fontFamily: "var(--sans)", fontSize: 13 }} placeholder="Comment for the agent…  (⌘↵ to save)"
        value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onSave(text);
          if (e.key === "Escape") onCancel();
        }} />
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <button className="btn sm primary" onClick={() => onSave(text)} disabled={!text.trim()}>Comment</button>
        <button className="btn sm ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function CommentCard({ c, reload, showLoc }: { c: Comment; reload: () => void; showLoc?: boolean }) {
  const { project } = useApp();
  const set = async (status: string) => { await patch(`/api/p/${project.id}/comments/${c.id}`, { status }); reload(); };
  return (
    <div className={`comment ${c.status}`}>
      <div className="body">
        {showLoc && <div className="mono muted" style={{ fontSize: 11.5 }}>{c.path}{c.line ? `:${c.line}` : ""}</div>}
        {c.text}
      </div>
      <span className={`pill ${c.status === "open" ? "running" : c.status === "sent" ? "killed" : "done"}`}>{c.status}</span>
      {c.status !== "resolved" ? <button className="btn sm ghost" onClick={() => set("resolved")}>Resolve</button>
        : <button className="btn sm ghost" onClick={() => set("open")}>Reopen</button>}
      <button className="btn sm ghost danger" onClick={async () => { await del(`/api/p/${project.id}/comments/${c.id}`); reload(); }}>×</button>
    </div>
  );
}
