import { useEffect, useMemo, useState } from "react";
import { del, fmtTime, post, put, tildify, useApi } from "../api";
import { linkProps, navigate } from "../router";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { TerminalView, type TermInfo } from "../components/TerminalPane";

interface Skill {
  id: string;
  name: string;
  description: string;
  source: "user" | "dsd" | "repo" | "plugin" | "claude.ai" | "pane";
  editable: boolean;
  path: string;
  files: number;
  updated: number | null;
  plugin?: string;
  repo?: string;
  projects?: string[];
}
type SkillDetail = Omit<Skill, "files"> & { files: { path: string; size: number }[] };

const SOURCES: [Skill["source"], string][] = [
  ["user", "Your skills"], ["dsd", "From dsd"], ["repo", "Repo skills"], ["plugin", "Plugins"], ["claude.ai", "From claude.ai"], ["pane", "Managed by Pane"],
];
const OWNER: Record<Skill["source"], string> = {
  user: "you", dsd: "dsd (your edits are kept by dsd setup)", repo: "the repo", plugin: "its plugin", "claude.ai": "claude.ai sync", pane: "Pane",
};

const skillHref = (id: string, file?: string) => `/skills/${id}${file && file !== "SKILL.md" ? `?file=${encodeURIComponent(file)}` : ""}`;

export function SkillsPage({ sid, file }: { sid: string | null; file: string | null }) {
  const skills = useApi<Skill[]>("/api/skills", { poll: 15000 });
  const terms = useApi<TermInfo[]>("/api/skills/terminals", { poll: 4000 });
  const [q, setQ] = useState("");
  const [activeTerm, setActiveTerm] = useState<string | null>(null);
  const bundled = useApi<{ name: string; state: "missing" | "current" | "outdated" | "edited" }[]>("/api/skills/dsd");
  const [installing, setInstalling] = useState(false);
  useEffect(() => { document.title = "Skills · dsd"; }, []);
  const pending = (bundled.data ?? []).filter((b) => b.state === "missing" || b.state === "outdated");
  const install = async () => {
    setInstalling(true);
    try {
      await post("/api/skills/dsd/install", { force: false });
      bundled.reload();
      skills.reload();
    } finally {
      setInstalling(false);
    }
  };

  const list = skills.data ?? [];
  const current = sid ?? list.find((s) => s.editable)?.id ?? list[0]?.id ?? null;
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? list.filter((s) => `${s.name} ${s.description}`.toLowerCase().includes(needle)) : list;
  }, [list, q]);
  const sessions = (terms.data ?? []).filter((t) => !t.exited || t.id === activeTerm);
  const active = sessions.find((t) => t.id === activeTerm) ?? sessions[sessions.length - 1] ?? null;

  const startSession = async (id: string, kind: "claude" | "shell") => {
    const t = await post<TermInfo>(`/api/skills/${id}/session`, { kind });
    await terms.reload();
    setActiveTerm(t.id);
  };
  const closeSession = async (id: string) => {
    await del(`/api/terminals/${id}`);
    terms.reload();
  };

  return (
    <div className="app" style={{ gridTemplateColumns: `216px minmax(0,1fr) ${sessions.length ? 560 : 0}px` }}>
      <aside className="sidebar">
        <a className="brand" {...linkProps("/")} style={{ color: "inherit", textDecoration: "none" }}><span className="logo">ds</span> dsd</a>
        <nav className="nav">
          <a {...linkProps("/")}><Icon name="home" /> Home</a>
          <a className="active" {...linkProps("/skills")}><Icon name="skill" /> Skills</a>
        </nav>
        {pending.length > 0 && (
          <div className="card" style={{ margin: "8px 10px 0", padding: "8px 10px", fontSize: 12.5 }}>
            <div>{pending.length} dsd skill{pending.length > 1 ? "s" : ""} {pending.every((b) => b.state === "missing") ? "not installed" : "to install or update"}:
              <span className="mono muted"> {pending.map((b) => b.name).join(", ")}</span></div>
            <button className="btn sm primary" style={{ marginTop: 6 }} disabled={installing} onClick={install}>
              {installing ? "Installing…" : "Install into ~/.claude/skills"}</button>
          </div>
        )}
        <div style={{ padding: "8px 10px 2px" }}>
          <input className="input" style={{ width: "100%" }} placeholder="Filter skills…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {SOURCES.map(([source, label]) => {
            const group = shown.filter((s) => s.source === source);
            if (!group.length) return null;
            return (
              <div key={source}>
                <div className="section-label" style={{ padding: "12px 16px 4px" }}>{label}</div>
                <nav className="nav">
                  {group.map((s) => (
                    <a key={s.id} className={s.id === current ? "active" : ""} {...linkProps(skillHref(s.id))} title={s.description}>
                      {s.name}
                      {s.source === "repo" && s.repo && <span className="count">{s.repo.split("/").pop()}</span>}
                    </a>
                  ))}
                </nav>
              </div>
            );
          })}
          {skills.data && list.length === 0 && <div className="empty">No skills found in ~/.claude/skills.</div>}
        </div>
      </aside>
      <main className="main">
        {current ? <SkillView key={current} sid={current} file={file} onSession={startSession} /> : <div className="empty">Loading…</div>}
      </main>
      {sessions.length > 0 && (
        <section className="agent">
          <div className="term-pane">
            <div className="term-tabs">
              {sessions.map((t) => (
                <button key={t.id} className={`term-tab ${t.id === active?.id ? "active" : ""}`} onClick={() => setActiveTerm(t.id)}>
                  <span className={`dot ${t.kind === "claude" ? "" : "shell"} ${t.exited ? "exited" : ""}`} />
                  {t.title}
                  <span className="x" onClick={(e) => { e.stopPropagation(); closeSession(t.id); }}>×</span>
                </button>
              ))}
            </div>
            <div className="term-body">
              {sessions.map((t) => (
                <TerminalView key={t.id} tid={t.id} active={t.id === active?.id} onExit={() => terms.reload()} />
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function SkillView({ sid, file, onSession }: { sid: string; file: string | null; onSession: (id: string, kind: "claude" | "shell") => void }) {
  const skill = useApi<SkillDetail>(`/api/skills/${sid}`, { poll: 8000 });
  const s = skill.data;
  const current = file ?? "SKILL.md";
  if (skill.error) return <div className="page"><div className="error-box">{skill.error}</div></div>;
  if (!s) return <div className="empty">Loading…</div>;
  const where = s.source === "plugin" ? s.plugin : s.source === "repo" ? s.projects?.join(", ") : null;
  return (
    <div className="page full" style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "16px 22px 10px" }}>
        <div className="page-head" style={{ marginBottom: 6 }}>
          <h1>{s.name}</h1>
          <span className="pill" title={`Owned by ${OWNER[s.source]}`}>{s.source}{where ? ` · ${where}` : ""}</span>
          {!s.editable && <span className="pill killed">read-only</span>}
          <span className="spacer" />
          <button className="btn" onClick={() => onSession(s.id, "shell")}>Shell</button>
          <button className="btn primary" onClick={() => onSession(s.id, "claude")}>Develop with Claude</button>
        </div>
        <div className="mono muted" style={{ fontSize: 12 }}>{tildify(s.path)}{s.updated ? ` · edited ${fmtTime(new Date(s.updated * 1000).toISOString())}` : ""}</div>
        {s.description && <p className="dim" style={{ margin: "10px 0 0", maxWidth: 900 }}>{s.description}</p>}
        {!s.editable && (
          <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
            Managed by {OWNER[s.source]}: local edits would be overwritten, so this skill is read-only here.
          </p>
        )}
      </div>
      <div className="split" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="pane-l">
          <div className="tree">
            {s.files.map((f) => (
              <button key={f.path} className={`tree-item ${f.path === current ? "active" : ""}`} title={f.path}
                onClick={() => navigate(skillHref(s.id, f.path))}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{f.path}</span>
                <span className="spacer" />
                <span className="muted mono" style={{ fontSize: 10.5 }}>{f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`}</span>
              </button>
            ))}
          </div>
          {s.editable && <NewFile sid={s.id} onCreated={(p) => { skill.reload(); navigate(skillHref(s.id, p)); }} />}
        </div>
        <div className="pane-r">
          <FileView key={current} sid={s.id} path={current} editable={s.editable} />
        </div>
      </div>
    </div>
  );
}

function NewFile({ sid, onCreated }: { sid: string; onCreated: (path: string) => void }) {
  const [path, setPath] = useState<string | null>(null);
  const create = async () => {
    let p = (path ?? "").trim();
    if (!p) return;
    if (!/\.\w+$/.test(p)) p += ".md";
    await put(`/api/skills/${sid}/file`, { path: p, content: "" });
    setPath(null);
    onCreated(p);
  };
  return path === null ? (
    <div style={{ padding: "8px 10px" }}><button className="btn sm ghost" onClick={() => setPath("references/")}>+ New file</button></div>
  ) : (
    <div style={{ padding: "8px 10px", display: "flex", gap: 6 }}>
      <input className="input mono" style={{ flex: 1, fontSize: 12 }} autoFocus value={path} onChange={(e) => setPath(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") setPath(null); }} />
      <button className="btn sm primary" onClick={create}>Create</button>
    </div>
  );
}

function FileView({ sid, path, editable }: { sid: string; path: string; editable: boolean }) {
  const doc = useApi<{ content: string }>(`/api/skills/${sid}/file?path=${encodeURIComponent(path)}`, { poll: 5000 });
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isMd = /\.(md|markdown)$/i.test(path);
  const editing = draft !== null;

  const save = async () => {
    if (draft === null) return;
    try {
      await put(`/api/skills/${sid}/file`, { path, content: draft });
      setDraft(null);
      setError(null);
      doc.reload();
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };
  const dirty = editing && doc.data && draft !== doc.data.content;

  return (
    <>
      <div className="doc-head">
        <span className="path">{path}</span>
        <span className="spacer" />
        {editable && !editing && <button className="btn sm" onClick={() => setDraft(doc.data?.content ?? "")}>Edit</button>}
        {editing && <>
          <button className="btn sm ghost" onClick={() => setDraft(null)}>Cancel</button>
          <button className="btn sm primary" onClick={save} disabled={!dirty}>Save</button>
        </>}
      </div>
      {error && <div className="doc-body" style={{ paddingBottom: 0 }}><div className="error-box">{error}</div></div>}
      {editing ? (
        <div className="editor">
          <textarea className="input" value={draft ?? ""} onChange={(e) => setDraft(e.target.value)} autoFocus
            onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } }} />
        </div>
      ) : doc.error ? (
        <div className="doc-body"><div className="error-box">{doc.error}</div></div>
      ) : !doc.data ? (
        <div className="empty">Loading…</div>
      ) : isMd ? (
        <div className="doc-body"><Markdown pid="skills" source={doc.data.content.replace(/^---\n[\s\S]*?\n---\n/, "")} docPath={null} /></div>
      ) : (
        <div className="doc-body"><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{doc.data.content}</pre></div>
      )}
    </>
  );
}
