import { useEffect, useMemo, useState } from "react";
import { api, put, useApi } from "../api";
import { useApp } from "../context";
import { href, navigate } from "../router";
import { Markdown } from "../components/Markdown";

interface DocFile { path: string; size: number; mtime: number }
interface TreeNode { name: string; path: string; children: Map<string, TreeNode>; file?: DocFile }

function buildTree(files: DocFile[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map() };
  for (const f of files) {
    const parts = f.path.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const p = parts.slice(0, i + 1).join("/");
      if (!node.children.has(part)) node.children.set(part, { name: part, path: p, children: new Map() });
      node = node.children.get(part)!;
      if (i === parts.length - 1) node.file = f;
    });
  }
  return root;
}

const ORDER = ["plans", "analytics", "decisions", "notes", "experiments", "reports"];

type PlanOrder = Map<string, { index: number; number: string }>;

function Tree({ node, depth, current, collapsed, toggle, plans }: {
  node: TreeNode; depth: number; current: string | null; collapsed: Set<string>; toggle: (p: string) => void; plans: PlanOrder;
}) {
  const { project } = useApp();
  const inPlans = node.path === "plans";
  const kids = Array.from(node.children.values()).sort((a, b) => {
    const ad = a.file ? 1 : 0, bd = b.file ? 1 : 0;
    if (ad !== bd) return ad - bd;
    if (depth === 0) {
      const ai = ORDER.indexOf(a.name), bi = ORDER.indexOf(b.name);
      if (ai !== bi) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    }
    if (inPlans) {
      const ai = plans.get(a.path)?.index ?? 999, bi = plans.get(b.path)?.index ?? 999;
      if (ai !== bi) return ai - bi;
    }
    return a.name.localeCompare(b.name);
  });
  return (
    <>
      {kids.map((k) => k.file ? (
        <button key={k.path} className={`tree-item ${current === k.path ? "active" : ""}`} style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => navigate(href(project.id, "docs", k.path))} title={k.path}>
          <span className="chev" />{plans.get(k.path)?.number ? <span className="plan-num mono">{plans.get(k.path)!.number}</span> : null}<span className="tree-name">{k.name}</span>
        </button>
      ) : (
        <div key={k.path}>
          <button className="tree-item" style={{ paddingLeft: 8 + depth * 14, fontWeight: 550 }} onClick={() => toggle(k.path)}>
            <span className="chev">{collapsed.has(k.path) ? "▶" : "▼"}</span>{k.name}
          </button>
          {!collapsed.has(k.path) && <Tree node={k} depth={depth + 1} current={current} collapsed={collapsed} toggle={toggle} plans={plans} />}
        </div>
      ))}
    </>
  );
}

export function Docs({ path }: { path: string | null }) {
  const { project, sendToAgent } = useApp();
  const files = useApi<DocFile[]>(`/api/p/${project.id}/docs`, { poll: 8000 });
  const planList = useApi<{ slug: string; number?: string }[]>(`/api/p/${project.id}/plans`, { poll: 15000 });
  const planOrder: PlanOrder = useMemo(
    () => new Map((planList.data ?? []).map((p, i) => [`plans/${p.slug}.md`, { index: i, number: p.number ?? "" }])),
    [planList.data]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState<string | null>(null);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(async () => setHits(await api(`/api/p/${project.id}/docs/search?q=${encodeURIComponent(q)}`)), 180);
    return () => clearTimeout(t);
  }, [q, project.id]);

  const tree = useMemo(() => buildTree(files.data ?? []), [files.data]);
  const current = path ?? (files.data?.find((f) => f.path === "plans/main.md") ? "plans/main.md" : files.data?.[0]?.path ?? null);

  const create = async () => {
    let p = (creating ?? "").trim();
    if (!p) return;
    if (!/\.\w+$/.test(p)) p += ".md";
    const title = p.split("/").pop()!.replace(/\.md$/, "").replace(/[-_]/g, " ");
    await put(`/api/p/${project.id}/docs/file`, { path: p, content: `# ${title[0].toUpperCase()}${title.slice(1)}\n\n` });
    setCreating(null);
    files.reload();
    navigate(href(project.id, "docs", p) + "?edit=1");
  };

  return (
    <div className="page full">
      <div className="split">
        <div className="pane-l">
          <div style={{ padding: "10px 10px 4px", display: "flex", gap: 6 }}>
            <input className="input" style={{ flex: 1 }} placeholder="Search docs…" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn" title="New doc" onClick={() => setCreating("notes/")}>+</button>
          </div>
          {creating !== null && (
            <div style={{ padding: "4px 10px", display: "flex", gap: 6 }}>
              <input className="input mono" style={{ flex: 1, fontSize: 12 }} autoFocus value={creating} onChange={(e) => setCreating(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") setCreating(null); }} />
              <button className="btn sm primary" onClick={create}>Create</button>
            </div>
          )}
          {hits ? (
            <div className="search-results">
              {hits.length === 0 && <div className="empty">No matches</div>}
              {hits.map((h) => (
                <div key={h.path} className="search-hit" onClick={() => navigate(href(project.id, "docs", h.path))}>
                  <div className="mono" style={{ fontSize: 12 }}>{h.path}</div>
                  {h.snippets.map((s: any) => <div key={s.line} className="snip">{s.line}: {s.text}</div>)}
                </div>
              ))}
            </div>
          ) : (
            <div className="tree">
              <Tree node={tree} depth={0} current={current} collapsed={collapsed} plans={planOrder}
                toggle={(p) => setCollapsed((c) => { const n = new Set(c); n.has(p) ? n.delete(p) : n.add(p); return n; })} />
            </div>
          )}
          <div className="muted" style={{ padding: "10px 14px", fontSize: 11.5 }}>
            <button className="btn sm ghost" onClick={() => sendToAgent("/dsd-distill ")}>Distill chat → doc</button>
            <button className="btn sm ghost" onClick={() => sendToAgent("/dsd-report ")}>New report</button>
          </div>
        </div>
        <div className="pane-r">
          {current ? <DocView key={current} path={current} onSaved={files.reload} /> : <div className="empty">No docs yet.</div>}
        </div>
      </div>
    </div>
  );
}

function DocView({ path, onSaved }: { path: string; onSaved: () => void }) {
  const { project, toast } = useApp();
  const isHtml = /\.html?$/i.test(path);
  const isImg = /\.(png|jpe?g|svg|gif|webp|pdf)$/i.test(path);
  const isMd = /\.(md|markdown)$/i.test(path);
  const doc = useApi<{ content: string }>(isImg ? null : `/api/p/${project.id}/docs/file?path=${encodeURIComponent(path)}`, { poll: 5000 });
  const [editing, setEditing] = useState(() => new URLSearchParams(window.location.search).get("edit") === "1");
  const [draft, setDraft] = useState<string | null>(null);
  const [frameKey, setFrameKey] = useState(0);

  useEffect(() => {
    if (editing && draft === null && doc.data) setDraft(doc.data.content);
  }, [editing, doc.data, draft]);

  const save = async () => {
    if (draft === null) return;
    await put(`/api/p/${project.id}/docs/file`, { path, content: draft });
    toast("Saved");
    setEditing(false);
    setDraft(null);
    doc.reload();
    onSaved();
  };
  const dirty = draft !== null && doc.data && draft !== doc.data.content;
  const raw = `/api/p/${project.id}/docs/raw/${path}`;

  return (
    <>
      <div className="doc-head">
        <span className="path">docs/{path}</span>
        <span className="spacer" />
        {isHtml && !editing && <button className="btn sm ghost" onClick={() => setFrameKey((k) => k + 1)}>Reload</button>}
        {(isHtml || isImg) && <a className="btn sm ghost" href={raw} target="_blank" rel="noreferrer">Open ↗</a>}
        {!isImg && !editing && <button className="btn sm" onClick={() => { setDraft(doc.data?.content ?? ""); setEditing(true); }}>Edit</button>}
        {editing && <>
          <button className="btn sm ghost" onClick={() => { setEditing(false); setDraft(null); }}>Cancel</button>
          <button className="btn sm primary" onClick={save} disabled={!dirty}>Save</button>
        </>}
      </div>
      {editing ? (
        <div className="editor">
          <textarea className="input" value={draft ?? ""} onChange={(e) => setDraft(e.target.value)} autoFocus
            onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } }} />
        </div>
      ) : isHtml ? (
        <iframe key={frameKey} className="doc-frame" src={raw} sandbox="allow-scripts allow-popups" title={path} />
      ) : isImg ? (
        <div className="doc-body"><img src={raw} alt={path} style={{ maxWidth: "100%" }} /></div>
      ) : doc.error ? (
        <div className="doc-body"><div className="error-box">{doc.error}</div></div>
      ) : !doc.data ? (
        <div className="empty">Loading…</div>
      ) : isMd ? (
        <div className="doc-body">
          <Markdown pid={project.id} source={doc.data.content.replace(/^---\n[\s\S]*?\n---\n/, "")} docPath={path} />
        </div>
      ) : (
        <div className="doc-body"><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{doc.data.content}</pre></div>
      )}
    </>
  );
}
