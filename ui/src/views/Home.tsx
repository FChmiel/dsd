import { useEffect, useMemo, useRef, useState } from "react";
import { del, fmtNum, fmtTime, patch, post, projectPath, useApi, type Project } from "../api";
import { href, linkProps, navigate } from "../router";
import { Icon } from "../components/Icon";
import { CliCard } from "../components/CliCard";
import { inApp, pickFolder } from "../native";

interface Todo {
  id: string;
  title: string;
  status: string;
  due: string | null;
  tags: string[];
  project: string | null;
  project_id: string | null;
  source: "home" | "project";
  plan: string;
  notes: string[];
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const parseIso = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const dayLabel = (s: string, today: Date) => {
  const d = parseIso(s);
  const diff = Math.round((d.getTime() - new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  if (diff > 1 && diff < 7) return d.toLocaleDateString(undefined, { weekday: "short" });
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

export function HomePage({ projects, reloadProjects }: { projects: Project[]; reloadProjects: () => void }) {
  const home = useApi<any>("/api/home", { poll: 10000 });
  const [toast, setToast] = useState<string | null>(null);
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast((c) => (c === m ? null : c)), 2200); };
  useEffect(() => { document.title = "Home · dsd"; }, []);
  useEffect(() => {
    if (window.location.hash === "#add-project" && home.data) {
      document.getElementById("add-project")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [home.data]);

  const d = home.data;
  return (
    <div className="app home-app" style={{ gridTemplateColumns: "216px minmax(0,1fr)" }}>
      <aside className="sidebar">
        <div className="brand"><span className="logo">ds</span> dsd</div>
        <nav className="nav">
          <a className="active" {...linkProps("/")}><Icon name="home" /> Home
            {d && d.counts.overdue + d.counts.today > 0 && <span className="count hot">{d.counts.overdue + d.counts.today}</span>}</a>
          <a {...linkProps("/skills")}><Icon name="skill" /> Skills</a>
        </nav>
        <div className="section-label" style={{ padding: "14px 16px 4px" }}>Projects</div>
        <nav className="nav">
          {projects.map((p) => {
            const s = d?.projects.find((x: any) => x.id === p.id);
            return (
              <a key={p.id} {...linkProps(href(p.id, "overview"))} title={projectPath(p)}>
                <span className="proj-dot" /> {p.name}
                {s?.doing?.length ? <span className="count">{s.doing.length}</span> : null}
              </a>
            );
          })}
          <a href="#add-project" onClick={(e) => { e.preventDefault(); document.getElementById("add-project")?.scrollIntoView({ behavior: "smooth" }); }}
            className="muted">+ Add project</a>
        </nav>
        <div className="sidebar-foot"><CliCard compact /></div>
      </aside>
      <main className="main">
        <div className="page home-page">
          <div className="home-head">
            <div>
              <h1>{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</h1>
              <div className="dim">{d ? d.summary : "Loading…"}</div>
            </div>
          </div>
          <QuickAdd onAdded={(t) => { home.reload(); flash(t.due ? `Added for ${dayLabel(t.due, new Date())}` : "Added to Someday"); }} />
          {home.error && <div className="error-box">{home.error}</div>}
          {d && (
            <div className="home-grid">
              <Agenda items={d.agenda} reload={home.reload} />
              <div className="stack">
                <NeedsYou items={d.attention} />
                <RecentDocs projects={d.projects} />
              </div>
            </div>
          )}
          {d && d.projects.length > 0 && (
            <>
              <div className="section-label" style={{ padding: "22px 0 8px" }}>Projects</div>
              <div className="grid-2">{d.projects.map((p: any) => <ProjectCard key={p.id} p={p} />)}</div>
            </>
          )}
          <AddProject reload={() => { reloadProjects(); home.reload(); }} />
          <ArchivedProjects reload={() => { reloadProjects(); home.reload(); }} />
          <CliCard />
        </div>
      </main>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function QuickAdd({ onAdded }: { onAdded: (t: Todo) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if ((e.key === "n" || e.key === "/") && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      const t = await post<Todo>("/api/todos", { text });
      setText("");
      onAdded(t);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="quick-add">
      <span className="plus">+</span>
      <input ref={ref} autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="Add a to-do…  e.g. “Send David the AUC numbers tomorrow #churn-model”" />
      <span className="hint">today · tomorrow · fri · next week · 11/24 · #project <span className="kbd">↵</span></span>
    </div>
  );
}

function Agenda({ items, reload }: { items: Todo[]; reload: () => void }) {
  const [showDone, setShowDone] = useState(false);
  const today = new Date();
  const t0 = iso(today);
  const week = iso(addDays(today, 7));
  const groups = useMemo(() => {
    const open = items.filter((t) => t.status !== "done" && t.status !== "dropped");
    const done = items.filter((t) => t.status === "done" || t.status === "dropped");
    const byDay = new Map<string, Todo[]>();
    open.filter((t) => t.due && t.due > t0 && t.due < week).forEach((t) => {
      byDay.set(t.due!, [...(byDay.get(t.due!) ?? []), t]);
    });
    const sortT = (a: Todo, b: Todo) => (a.source === b.source ? a.id.localeCompare(b.id, undefined, { numeric: true }) : a.source === "home" ? -1 : 1);
    const out: { key: string; label: string; items: Todo[]; tone?: string }[] = [
      { key: "overdue", label: "Overdue", items: open.filter((t) => t.due && t.due < t0).sort((a, b) => a.due!.localeCompare(b.due!)), tone: "bad" },
      { key: "today", label: "Today", items: open.filter((t) => t.due === t0).sort(sortT), tone: "accent" },
      ...Array.from(byDay.keys()).sort().map((k) => ({ key: k, label: dayLabel(k, today), items: byDay.get(k)!.sort(sortT) })),
      { key: "later", label: "Later", items: open.filter((t) => t.due && t.due >= week).sort((a, b) => a.due!.localeCompare(b.due!)) },
      { key: "someday", label: "Someday", items: open.filter((t) => !t.due).sort(sortT) },
    ];
    return { list: out.filter((g) => g.items.length || g.key === "today"), done };
  }, [items, t0, week]);

  return (
    <div className="card agenda">
      <div className="card-head">Agenda <span className="spacer" />
        {groups.done.length > 0 && (
          <button className="btn sm ghost" onClick={() => setShowDone((s) => !s)}>{showDone ? "Hide" : "Show"} done ({groups.done.length})</button>
        )}
      </div>
      <div className="card-body" style={{ paddingTop: 4 }}>
        {groups.list.map((g) => (
          <div key={g.key} className="agenda-group">
            <div className={`agenda-label ${g.tone ?? ""}`}>{g.label}<span className="muted"> {g.items.length || ""}</span></div>
            {g.items.length === 0 && g.key === "today" && <div className="muted agenda-empty">Nothing scheduled. Add something above, or pull it in from Someday.</div>}
            {g.items.map((t) => <TodoRow key={`${t.source}-${t.project_id}-${t.id}`} t={t} reload={reload} />)}
          </div>
        ))}
        {showDone && (
          <div className="agenda-group">
            <div className="agenda-label">Done</div>
            {groups.done.map((t) => <TodoRow key={`${t.source}-${t.project_id}-${t.id}`} t={t} reload={reload} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function TodoRow({ t, reload }: { t: Todo; reload: () => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(t.title);
  const [menu, setMenu] = useState(false);
  const done = t.status === "done" || t.status === "dropped";
  const isHome = t.source === "home";
  const today = new Date();
  const overdue = !done && t.due && t.due < iso(today);

  const toggle = async () => {
    const status = done ? "todo" : "done";
    if (isHome) await patch(`/api/todos/${t.id}`, { status });
    else await patch(`/api/p/${t.project_id}/tasks/${t.id}`, { status });
    reload();
  };
  const setDue = async (due: string | null) => {
    setMenu(false);
    await patch(`/api/todos/${t.id}`, { due });
    reload();
  };
  const saveTitle = async () => {
    setEditing(false);
    if (title.trim() && title.trim() !== t.title) {
      await patch(`/api/todos/${t.id}`, { title: title.trim() });
      reload();
    }
  };

  return (
    <div className={`todo ${done ? "done" : ""}`}>
      <button className={`todo-check ${done ? "on" : ""}`} onClick={toggle} title={done ? "Mark not done" : "Mark done"} />
      <div className="todo-main">
        {editing ? (
          <input className="input" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onBlur={saveTitle}
            onKeyDown={(e) => { if (e.key === "Enter") saveTitle(); if (e.key === "Escape") { setTitle(t.title); setEditing(false); } }} />
        ) : (
          <span className="todo-title" onDoubleClick={() => isHome && setEditing(true)} title={isHome ? "Double-click to edit" : undefined}>{t.title}</span>
        )}
        <span className="todo-meta">
          {!isHome && t.project_id && (
            <a className="chip proj" {...linkProps(`${href(t.project_id, "plans", t.plan)}?task=${t.id}`)}>{t.project} · {t.id}</a>
          )}
          {isHome && t.project && <span className="chip proj">{t.project}</span>}
          {t.tags.map((g) => <span key={g} className="tag">#{g}</span>)}
        </span>
      </div>
      <div className="todo-due">
        {isHome ? (
          <button className={`chip due ${overdue ? "overdue" : ""}`} onClick={() => setMenu((m) => !m)}>
            {t.due ? dayLabel(t.due, today) : "＋ day"}
          </button>
        ) : t.due ? <span className={`chip due ${overdue ? "overdue" : ""}`}>{dayLabel(t.due, today)}</span> : null}
        {menu && <DueMenu onPick={setDue} onClose={() => setMenu(false)} current={t.due} />}
      </div>
      {isHome ? <button className="todo-x" title="Delete" onClick={async () => { await del(`/api/todos/${t.id}`); reload(); }}>×</button>
        : <span className="todo-x" aria-hidden />}
    </div>
  );
}

function DueMenu({ onPick, onClose, current }: { onPick: (d: string | null) => void; onClose: () => void; current: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [onClose]);
  const today = new Date();
  const nextMon = addDays(today, ((8 - today.getDay()) % 7) || 7);
  const opts: [string, string | null][] = [
    ["Today", iso(today)], ["Tomorrow", iso(addDays(today, 1))],
    [`This ${today.getDay() >= 5 || today.getDay() === 0 ? "next " : ""}Friday`, iso(addDays(today, ((12 - today.getDay()) % 7) || 7))],
    ["Next week", iso(nextMon)], ["Someday", null],
  ];
  return (
    <div className="due-menu" ref={ref}>
      {opts.map(([label, v]) => (
        <button key={label} className={`menu-item ${v === current ? "active" : ""}`} onClick={() => onPick(v)}>
          {label}<span className="muted" style={{ float: "right" }}>{v ? dayLabel(v, today) : ""}</span>
        </button>
      ))}
      <input type="date" className="input" style={{ width: "100%", marginTop: 4 }} defaultValue={current ?? ""}
        onChange={(e) => e.target.value && onPick(e.target.value)} />
    </div>
  );
}

const ATTN_ICON: Record<string, string> = { blocked: "!", merge: "⇡", uncommitted: "●", failed: "✕", comments: "✎", error: "?" };

function NeedsYou({ items }: { items: any[] }) {
  return (
    <div className="card">
      <div className="card-head">Needs you <span className="sub">{items.length || ""}</span></div>
      {items.length === 0 ? <div className="empty">All clear across projects.</div> : (
        <div className="attn-list">
          {items.map((a, i) => {
            const to = a.kind === "blocked" ? `${href(a.project_id, "plans")}?task=${a.task}`
              : a.kind === "merge" || a.kind === "uncommitted" ? href(a.project_id, "worktrees")
              : a.kind === "failed" ? href(a.project_id, "runs", a.run)
              : a.kind === "comments" ? href(a.project_id, "changes") : href(a.project_id, "overview");
            return (
              <a key={i} className={`attn ${a.kind}`} {...linkProps(to)}>
                <span className="attn-ic">{ATTN_ICON[a.kind] ?? "•"}</span>
                <span><span className="attn-proj">{a.project}</span> {a.text}</span>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RecentDocs({ projects }: { projects: any[] }) {
  const docs = projects.flatMap((p) => (p.recent_docs ?? []).map((d: any) => ({ ...d, project: p.name, project_id: p.id })))
    .sort((a, b) => b.mtime - a.mtime).slice(0, 8);
  return (
    <div className="card">
      <div className="card-head">Recent docs <span className="sub">designs, decisions, analysis</span></div>
      {docs.length === 0 ? <div className="empty">No docs edited in the last two weeks.</div> : (
        <div className="attn-list">
          {docs.map((d) => (
            <a key={`${d.project_id}/${d.path}`} className="attn" {...linkProps(href(d.project_id, "docs", d.path))}>
              <span className="attn-ic doc">{d.path.endsWith(".html") ? "◧" : "¶"}</span>
              <span style={{ minWidth: 0 }}>
                <span className="attn-proj">{d.project}</span> {d.path.split("/").pop()!.replace(/\.(md|html)$/, "")}
                <span className="muted" style={{ fontSize: 11.5 }}> · {d.path.includes("/") ? d.path.split("/")[0] : "docs"} · {fmtTime(new Date(d.mtime * 1000).toISOString())}</span>
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ p }: { p: any }) {
  if (p.error) return <div className="card"><div className="card-head">{p.name}</div><div className="card-body error-box">{p.error}</div></div>;
  const c = p.counts;
  const total = c.todo + c.doing + c.blocked + c.done || 1;
  const pct = (n: number) => `${(n / total) * 100}%`;
  const lr = p.last_run;
  const metric = lr ? Object.entries(lr.metrics ?? {})[0] as [string, number] | undefined : undefined;
  return (
    <div className="card proj-card">
      <div className="card-head">
        <a {...linkProps(href(p.id, "overview"))} style={{ color: "inherit" }}>{p.name}</a>
        {p.sessions > 0 && <span className="pill running">{p.sessions} session{p.sessions > 1 ? "s" : ""}</span>}
        <span className="spacer" />
        <button className="btn sm" onClick={() => navigate(href(p.id, "overview"))}>Open</button>
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        <div>
          <div className="progress" aria-label={`${c.done} of ${total} done`}>
            <span style={{ width: pct(c.done), background: "var(--ok)" }} />
            <span style={{ width: pct(c.doing), background: "var(--doing)" }} />
            <span style={{ width: pct(c.blocked), background: "var(--bad)" }} />
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{c.done}/{total} done · {c.doing} in progress{c.blocked ? ` · ${c.blocked} blocked` : ""}</div>
        </div>
        {p.doing.length > 0 && (
          <div>
            {p.doing.slice(0, 3).map((t: any) => (
              <a key={t.id} className="mini-task" {...linkProps(`${href(p.id, "plans", t.plan)}?task=${t.id}`)}>
                <span className="status-btn doing" /> <span className="id">{t.id}</span> {t.title}
              </a>
            ))}
          </div>
        )}
        <div className="proj-facts">
          {lr && (
            <a {...linkProps(href(p.id, "runs", lr.id))}>
              <span className={`pill ${lr.status}`}>{lr.status}</span> {lr.name}{metric ? <span className="muted"> · {metric[0]} {fmtNum(metric[1])}</span> : null}
              <span className="muted"> · {fmtTime(lr.created_at)}</span>
            </a>
          )}
          {p.worktrees.length > 0 && (
            <a {...linkProps(href(p.id, "worktrees"))}>
              ⎇ {p.worktrees.length} worktree{p.worktrees.length > 1 ? "s" : ""}
              {p.worktrees.some((w: any) => w.ahead && !w.dirty) ? <span className="muted"> · ready to merge</span> : null}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function AddProject({ reload }: { reload: () => void }) {
  const [path, setPath] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [needsInit, setNeedsInit] = useState(false);
  const [scope, setScope] = useState("");
  const add = async (init = false, override?: string) => {
    setErr(null);
    try {
      const p = await post<Project>("/api/projects", { path: override ?? path, init, scope: init && scope.trim() ? scope.trim() : null });
      reload();
      navigate(href(p.id, "overview"));
    } catch (e: any) {
      if (e.status === 409) setNeedsInit(true);
      setErr(e.message);
    }
  };
  return (
    <div className="card" id="add-project" style={{ marginTop: 22 }}>
      <div className="card-head">Add a project</div>
      <div className="card-body" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="input" style={{ flex: 1, minWidth: 240 }} placeholder="/path/to/repo" value={path}
          onChange={(e) => { setPath(e.target.value); setNeedsInit(false); }} onKeyDown={(e) => e.key === "Enter" && add()} />
        {inApp && <button className="btn" onClick={async () => {
          const dir = await pickFolder();
          if (dir) { setPath(dir); setNeedsInit(false); add(false, dir); }
        }}>Choose folder…</button>}
        <button className="btn primary" onClick={() => add()}>Open</button>
      </div>
      {needsInit && (
        <div className="card-body" style={{ paddingTop: 0, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span className="muted" style={{ flexBasis: "100%" }}>
            No dsd project for this folder yet. Start one? Its docs, plans and runs are kept in <code>~/.dsd</code>; nothing is written to the repo.
          </span>
          <input className="input" style={{ flex: 1, minWidth: 200 }} placeholder="Scope: subdirectory, optional (e.g. apps/churn)" value={scope}
            onChange={(e) => setScope(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add(true)} />
          <button className="btn" onClick={() => add(true)}>Start a dsd project</button>
        </div>
      )}
      {err && !needsInit && <div className="card-body" style={{ paddingTop: 0 }}><div className="error-box">{err}</div></div>}
    </div>
  );
}

function ArchivedProjects({ reload }: { reload: () => void }) {
  const archived = useApi<(Project & { archived_at: string | null })[]>("/api/projects/archived");
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const list = archived.data ?? [];
  if (!list.length) return null;
  const restore = async (p: Project) => {
    setMsg(null);
    try {
      const r = await post<{ restored: string[]; missing: string[] }>(`/api/projects/${p.id}/restore`, {});
      archived.reload();
      reload();
      setMsg(`Restored ${p.name}` + (r.restored.length ? ` with ${r.restored.join(", ")}` : "")
        + (r.missing.length ? `; branch gone for ${r.missing.join(", ")}` : ""));
    } catch (e: any) {
      setMsg(e.message || String(e));
    }
  };
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-head" style={{ cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        Archived projects <span className="muted">{list.length}</span><span className="spacer" /><span className="muted">{open ? "▾" : "▸"}</span>
      </div>
      {open && (
        <div className="card-body stack" style={{ gap: 6 }}>
          {list.map((p) => (
            <div key={p.id} style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <b>{p.name}</b>
              <span className="muted mono" style={{ fontSize: 12 }}>{projectPath(p)}</span>
              {p.archived_at && <span className="muted" style={{ fontSize: 12 }}>archived {fmtTime(p.archived_at)}</span>}
              <span className="spacer" />
              <button className="btn sm" onClick={() => restore(p)}>Restore</button>
            </div>
          ))}
          {msg && <div className="muted">{msg}</div>}
        </div>
      )}
    </div>
  );
}
