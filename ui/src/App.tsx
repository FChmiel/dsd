import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, del, post, projectPath, qs, tildify, useApi, type Project } from "./api";
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
import { CliCard } from "./components/CliCard";
import { HomePage } from "./views/Home";
import { SkillsPage } from "./views/Skills";

const NAV = [
  { view: "overview", label: "Overview", icon: "grid" },
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

  if (route.view === "skills") return <SkillsPage sid={route.rest[0] ?? null} file={route.query.get("file")} />;
  if (!route.pid || (projects.data && !project)) {
    return <HomePage projects={projects.data ?? []} reloadProjects={projects.reload} />;
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
  const [agentFull, setAgentFull] = useState<boolean>(() => load("dsd.pane.full", false));
  const full = agentFull && paneOpen;
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [currentWt, setCurrentWt] = useState<string | null>(null);
  const active = terminals.find((t) => t.id === activeTerm);
  const focusWorktree = active ? active.worktree ?? null : currentWt;
  const overview = useApi<any>(`/api/p/${project.id}/overview${qs({ worktree: focusWorktree })}`, { poll: 6000 });
  useEffect(() => { if (overview.data) setCurrentWt(overview.data.current_worktree ?? null); }, [overview.data]);

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
  useEffect(() => save("dsd.pane.full", agentFull), [agentFull]);
  useEffect(() => { document.title = `${project.name} · dsd`; }, [project.name]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setPaneOpen((o) => !o);
      } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "Enter") {
        e.preventDefault();
        setPaneOpen(true);
        setAgentFull((f) => !f);
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
    project, sendToAgent, terminals, activeTerminal: activeTerm, focusWorktree, toast, newSession: newTerminal,
    openLauncher: () => { setPaneOpen(true); setLauncherOpen(true); },
  }), [project, sendToAgent, terminals, activeTerm, focusWorktree, toast, newTerminal]);

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
      <div className={`app ${full ? "agent-full" : ""}`}
        style={{ gridTemplateColumns: full ? "minmax(0,1fr)" : `216px minmax(0,1fr) ${paneOpen ? paneWidth : 0}px` }}>
        <aside className="sidebar">
          <a className="brand" {...linkProps("/")} style={{ color: "inherit", textDecoration: "none" }}><span className="logo">ds</span> dsd</a>
          <nav className="nav" style={{ paddingBottom: 6 }}>
            <a {...linkProps("/")}><Icon name="home" /> Home</a>
            <a {...linkProps("/skills")}><Icon name="skill" /> Skills</a>
          </nav>
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
            <div className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              title={`${projectPath(project)}\nDocs, plans and runs: ${tildify(project.data_dir)}`}>
              {projectPath(project)}
            </div>
            {focusWorktree && <div className="mono dim" style={{ marginTop: 2 }} title="The worktree of the active session">⎇ {focusWorktree}</div>}
            <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center" }}>
              <button className="btn sm ghost" onClick={() => setPaneOpen((o) => !o)}>
                {paneOpen ? "Hide" : "Show"} agent <span className="kbd">⌘J</span>
              </button>
              <CliCard compact />
            </div>
          </div>
        </aside>
        <main className="main">{body}</main>
        <section className={`agent ${paneOpen ? "" : "collapsed"}`} style={{ width: full ? "auto" : paneOpen ? paneWidth : 0 }}>
          {paneOpen && !full && (
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
            onTerminal={() => newTerminal("shell", focusWorktree ? { mode: "existing", worktree: focusWorktree } : { mode: "main" })}
            terminalWhere={focusWorktree ?? "main checkout"}
            onClose={closeTerminal}
            onExited={() => refreshTerms()}
            onHide={() => { setPaneOpen(false); setAgentFull(false); }}
            full={full}
            onToggleFull={() => setAgentFull((f) => !f)}
            context={`${project.name}${focusWorktree ? ` · ⎇ ${focusWorktree}` : ""}`}
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
              <div className="muted mono" style={{ fontSize: 11 }}>{projectPath(p)}</div>
            </button>
          ))}
          <div style={{ borderTop: "1px solid var(--border)", margin: "4px 0" }} />
          <button className="menu-item" onClick={async () => {
            setOpen(false);
            const name = window.prompt(`Name of the new project on ${projectPath(current)}`)?.trim();
            if (!name) return;
            const p = await post<Project>("/api/projects", { path: current.repo, init: true, name, scope: current.scope });
            window.location.assign(href(p.id, "overview"));
          }}>+ New project on this repo…</button>
          <button className="menu-item" onClick={() => { setOpen(false); navigate("/#add-project"); }}>+ Add project…</button>
        </div>
      )}
    </div>
  );
}
