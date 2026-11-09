import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, del, post, useApi, type Project } from "./api";
import { href, linkProps, navigate, useRoute } from "./router";
import { Ctx, type AppCtx } from "./context";
import { TerminalPane, type TermInfo } from "./components/TerminalPane";
import { Icon } from "./components/Icon";
import { Overview } from "./views/Overview";
import { Plans } from "./views/Plans";
import { Docs } from "./views/Docs";
import { Runs } from "./views/Runs";
import { RunDetail } from "./views/RunDetail";
import { Compare } from "./views/Compare";
import { Benchmarks } from "./views/Benchmarks";
import { Changes } from "./views/Changes";
import { Worktrees } from "./views/Worktrees";
import { loadSessionDefault, type SessionTarget } from "./components/SessionLauncher";
import { inApp, pickFolder } from "./native";

const NAV = [
  { view: "overview", label: "Overview", icon: "home" },
  { view: "plans", label: "Plans", icon: "list" },
  { view: "docs", label: "Docs", icon: "doc" },
  { view: "runs", label: "Runs", icon: "flask" },
  { view: "benchmarks", label: "Benchmarks", icon: "trophy" },
  { view: "changes", label: "Changes", icon: "diff" },
  { view: "worktrees", label: "Worktrees", icon: "branch" },
] as const;

function load<T>(k: string, d: T): T {
  try {
    const v = localStorage.getItem(k);
    return v === null ? d : (JSON.parse(v) as T);
  } catch {
    return d;
  }
}
function save(k: string, v: unknown) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ }
}

export default function App() {
  const route = useRoute();
  const projects = useApi<Project[]>("/api/projects");
  const project = projects.data?.find((p) => p.id === route.pid) ?? null;

  useEffect(() => {
    if (route.pid === null && projects.data?.length === 1) navigate(href(projects.data[0].id, "overview"), true);
  }, [route.pid, projects.data]);

  if (!route.pid || (projects.data && !project)) {
    return <Home projects={projects.data ?? []} reload={projects.reload} missing={!!route.pid} />;
  }
  if (!project) return <div className="empty">Loading…</div>;
  return <Workspace key={project.id} project={project} projects={projects.data!} />;
}

function Workspace({ project, projects }: { project: Project; projects: Project[] }) {
  const route = useRoute();
  const [terminals, setTerminals] = useState<TermInfo[]>([]);
  const [activeTerm, setActiveTerm] = useState<string | null>(null);
  const [paneOpen, setPaneOpen] = useState<boolean>(() => load("dsd.pane.open", true));
  const [paneWidth, setPaneWidth] = useState<number>(() => load("dsd.pane.width", 560));
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const overview = useApi<any>(`/api/p/${project.id}/overview`, { poll: 6000 });

  const toast = useCallback((m: string) => {
    setToastMsg(m);
    window.setTimeout(() => setToastMsg((cur) => (cur === m ? null : cur)), 2600);
  }, []);

  const refreshTerms = useCallback(async () => {
    const list = await api<TermInfo[]>(`/api/p/${project.id}/terminals`);
    setTerminals(list);
    setActiveTerm((cur) => (cur && list.some((t) => t.id === cur) ? cur : list[list.length - 1]?.id ?? null));
    return list;
  }, [project.id]);

  useEffect(() => { refreshTerms(); }, [refreshTerms]);
  useEffect(() => save("dsd.pane.open", paneOpen), [paneOpen]);
  useEffect(() => save("dsd.pane.width", paneWidth), [paneWidth]);
  useEffect(() => { document.title = `${project.name} · dsd`; }, [project.name]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setPaneOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const newTerminal = useCallback(async (kind: "claude" | "shell", target: SessionTarget = { mode: "main" }) => {
    const body: any = { kind };
    if (target.mode === "existing") body.worktree = target.worktree;
    if (target.mode === "new") body.new_worktree = { name: target.name, base: target.base, task: target.task, task_title: target.task_title };
    if (target.mode === "new") toast("Creating worktree…");
    const t = await post<TermInfo>(`/api/p/${project.id}/terminals`, body);
    setTerminals((ts) => [...ts, t]);
    setActiveTerm(t.id);
    setPaneOpen(true);
    if (t.worktree) toast(`${kind === "claude" ? "Claude" : "Shell"} started in worktree ${t.worktree} (${t.branch})`);
    return t;
  }, [project.id, toast]);

  const closeTerminal = useCallback(async (id: string) => {
    await del(`/api/terminals/${id}`);
    refreshTerms();
  }, [refreshTerms]);

  const sendToAgent = useCallback<AppCtx["sendToAgent"]>(async (text, opts = {}) => {
    let tid: string | null | undefined = opts.terminalId ?? null;
    let fresh = false;
    const live = terminals.filter((t) => !t.exited);
    if (!tid && opts.session) {
      // a dedicated session, e.g. a task's own worktree: reuse its Claude terminal if one is open
      const s = opts.session;
      const wanted = s.mode === "existing" ? s.worktree : s.mode === "main" ? null : undefined;
      const reuse = live.find((t) => t.kind === "claude" && (
        (wanted !== undefined && (t.worktree ?? null) === wanted) ||
        (s.mode === "new" && s.task && (t.worktree === s.task.toLowerCase() || !!t.worktree?.startsWith(`${s.task.toLowerCase()}-`)))));
      if (reuse) tid = reuse.id;
      else {
        tid = (await newTerminal("claude", s)).id;
        fresh = true;
      }
    }
    if (!tid) tid = activeTerm;
    if (!tid || !live.some((t) => t.id === tid)) {
      const claude = live.find((t) => t.kind === "claude");
      if (claude) tid = claude.id;
      else if (!fresh) {
        tid = (await newTerminal("claude", loadSessionDefault() === "new" ? { mode: "new" } : { mode: "main" })).id;
        fresh = true;
      }
    }
    setPaneOpen(true);
    setActiveTerm(tid);
    if (fresh) {
      toast("Starting Claude…");
      await new Promise((r) => setTimeout(r, 4500));
    }
    await post(`/api/terminals/${tid}/input`, { text, submit: !!opts.submit });
    toast(opts.submit ? "Sent to agent" : "Pasted into agent — press Enter to send");
  }, [activeTerm, terminals, newTerminal, toast]);

  const ctx = useMemo<AppCtx>(() => ({
    project, sendToAgent, terminals, activeTerminal: activeTerm, toast, newSession: newTerminal,
    openLauncher: () => { setPaneOpen(true); setLauncherOpen(true); },
  }), [project, sendToAgent, terminals, activeTerm, toast, newTerminal]);

  // pane resize
  const dragging = useRef(false);
  const [dragActive, setDragActive] = useState(false);
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (!dragging.current) return;
      setPaneWidth(Math.min(Math.max(window.innerWidth - e.clientX, 320), window.innerWidth - 480));
    };
    const up = () => {
      dragging.current = false;
      setDragActive(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);

  const ov = overview.data;
  const counts: Record<string, { n: number; hot?: boolean } | undefined> = {
    plans: ov ? { n: ov.in_progress.length, hot: ov.in_progress.length > 0 } : undefined,
    changes: ov ? { n: ov.changes, hot: ov.open_comments > 0 } : undefined,
    worktrees: ov ? { n: ov.worktrees ?? 0 } : undefined,
    benchmarks: ov ? { n: ov.benchmarks.length } : undefined,
  };

  let body: React.ReactNode;
  switch (route.view) {
    case "plans": body = <Plans slug={route.rest[0] ?? "main"} focus={route.query.get("task")} />; break;
    case "docs": body = <Docs path={route.rest.join("/") || null} />; break;
    case "runs": body = route.rest[0] ? <RunDetail rid={route.rest[0]} tab={route.query.get("tab")} /> : <Runs />; break;
    case "compare": body = <Compare ids={(route.query.get("ids") || "").split(",").filter(Boolean)} />; break;
    case "benchmarks": body = <Benchmarks name={route.rest[0] ?? null} />; break;
    case "changes": body = <Changes />; break;
    case "worktrees": body = <Worktrees />; break;
    default: body = <Overview data={ov} reload={overview.reload} />;
  }

  return (
    <Ctx.Provider value={ctx}>
      <div className="app" style={{ gridTemplateColumns: `216px minmax(0,1fr) ${paneOpen ? paneWidth : 0}px` }}>
        <aside className="sidebar">
          <div className="brand"><span className="logo">ds</span> dsd</div>
          <ProjectSwitcher current={project} projects={projects} />
          <nav className="nav">
            {NAV.map((n) => {
              const active = route.view === n.view || (n.view === "runs" && route.view === "compare");
              const c = counts[n.view];
              return (
                <a key={n.view} className={active ? "active" : ""} {...linkProps(href(project.id, n.view))}>
                  <Icon name={n.icon} /> {n.label}
                  {c && c.n > 0 && <span className={`count ${c.hot ? "hot" : ""}`}>{c.n}</span>}
                </a>
              );
            })}
          </nav>
          <div className="sidebar-foot">
            <div className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={project.root}>
              {project.root.replace(/^\/Users\/[^/]+/, "~")}
            </div>
            <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center" }}>
              <button className="btn sm ghost" onClick={() => setPaneOpen((o) => !o)}>
                {paneOpen ? "Hide" : "Show"} agent <span className="kbd">⌘J</span>
              </button>
              <CliCard compact />
            </div>
          </div>
        </aside>
        <main className="main">{body}</main>
        <section className={`agent ${paneOpen ? "" : "collapsed"}`} style={{ width: paneOpen ? paneWidth : 0 }}>
          {paneOpen && (
            <div className={`resizer ${dragActive ? "active" : ""}`} onMouseDown={() => {
              dragging.current = true;
              setDragActive(true);
              document.body.style.cursor = "col-resize";
              document.body.style.userSelect = "none";
            }} />
          )}
          <TerminalPane
            pid={project.id}
            launcherOpen={launcherOpen}
            setLauncherOpen={setLauncherOpen}
            terminals={terminals}
            activeId={activeTerm}
            onSelect={setActiveTerm}
            onNew={newTerminal}
            onClose={closeTerminal}
            onExited={() => refreshTerms()}
            onHide={() => setPaneOpen(false)}
          />
        </section>
      </div>
      {toastMsg && <div className="toast">{toastMsg}</div>}
    </Ctx.Provider>
  );
}

function ProjectSwitcher({ current, projects }: { current: Project; projects: Project[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, []);
  return (
    <div className="project-switch" ref={ref}>
      <button onClick={() => setOpen((o) => !o)}>
        <b style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{current.name}</b>
        <span className="muted">▾</span>
      </button>
      {open && (
        <div className="menu">
          {projects.map((p) => (
            <button key={p.id} className={`menu-item ${p.id === current.id ? "active" : ""}`}
              onClick={() => { setOpen(false); navigate(href(p.id, "overview")); }}>
              <div>{p.name}</div>
              <div className="muted mono" style={{ fontSize: 11 }}>{p.root.replace(/^\/Users\/[^/]+/, "~")}</div>
            </button>
          ))}
          <div style={{ borderTop: "1px solid var(--border)", margin: "4px 0" }} />
          <button className="menu-item" onClick={() => { setOpen(false); navigate("/"); }}>+ Add project…</button>
        </div>
      )}
    </div>
  );
}

function Home({ projects, reload, missing }: { projects: Project[]; reload: () => void; missing: boolean }) {
  const [path, setPath] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [needsInit, setNeedsInit] = useState(false);
  const add = async (init = false, override?: string) => {
    setErr(null);
    try {
      const p = await post<Project>("/api/projects", { path: override ?? path, init });
      reload();
      navigate(href(p.id, "overview"));
    } catch (e: any) {
      if (e.status === 409) setNeedsInit(true);
      setErr(e.message);
    }
  };
  return (
    <div className="home">
      <h1><span className="logo" style={{ display: "inline-grid", placeItems: "center", width: 30, height: 30, borderRadius: 8, background: "var(--accent)", color: "white", font: "700 13px var(--mono)", marginRight: 10, verticalAlign: -6 }}>ds</span>dsd</h1>
      <p className="dim">Plans, docs and experiments for agentic data science.</p>
      {missing && <div className="error-box">That project isn't registered on this machine.</div>}
      <div className="card">
        <div className="card-head">Projects</div>
        {projects.length === 0 && <div className="empty">No projects yet. Run <code>dsd init</code> in a repo, or add one below.</div>}
        {projects.map((p) => (
          <a key={p.id} className="menu-item" style={{ padding: "10px 14px" }} {...linkProps(href(p.id, "overview"))}>
            <b>{p.name}</b> <span className="muted mono" style={{ fontSize: 11.5, marginLeft: 8 }}>{p.root}</span>
          </a>
        ))}
      </div>
      <div className="card">
        <div className="card-head">Add a project</div>
        <div className="card-body" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input className="input" style={{ flex: 1, minWidth: 240 }} placeholder="/path/to/repo" value={path}
            onChange={(e) => { setPath(e.target.value); setNeedsInit(false); }} onKeyDown={(e) => e.key === "Enter" && add()} />
          {inApp && <button className="btn" onClick={async () => {
            const dir = await pickFolder();
            if (dir) { setPath(dir); setNeedsInit(false); add(false, dir); }
          }}>Choose folder…</button>}
          <button className="btn primary" onClick={() => add()}>Open</button>
          {needsInit && <button className="btn" onClick={() => add(true)}>Set up dsd here</button>}
        </div>
        {err && <div className="card-body"><div className="error-box">{err}</div></div>}
      </div>
      <CliCard />
    </div>
  );
}

/** Packaged app only: offer to link the bundled `dsd` CLI onto PATH if it isn't there. */
export function CliCard({ compact }: { compact?: boolean }) {
  const cli = useApi<any>(inApp ? "/api/cli" : null);
  const [msg, setMsg] = useState<string | null>(null);
  if (!inApp || !cli.data?.frozen || cli.data.on_path) return null;
  const install = async () => {
    try {
      const r = await post<any>("/api/cli/install", {});
      setMsg(r.on_path ? `Installed: ${r.linked}` : `Linked ${r.linked}. ${r.hint}`);
      cli.reload();
    } catch (e: any) { setMsg(e.message); }
  };
  if (compact) {
    return <button className="btn sm ghost" title="Link the bundled dsd command into ~/.local/bin so Claude Code outside the app can use it" onClick={install}>Install dsd command</button>;
  }
  return (
    <div className="card">
      <div className="card-head">Command-line tool</div>
      <div className="card-body">
        <p className="dim" style={{ marginTop: 0 }}>
          Sessions inside the app already have <code>dsd</code>. To use <code>dsd exec</code>, <code>dsd wt</code> and the MCP server from
          your own terminal or editor, link the bundled command into <code>~/.local/bin</code>.
        </p>
        <button className="btn" onClick={install}>Install dsd command</button>
        {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
      </div>
    </div>
  );
}
