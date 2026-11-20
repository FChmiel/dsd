import { useEffect, useMemo, useState } from "react";
import { del, patch, post, put, useApi, type Task, type TaskStatus } from "../api";
import { useApp } from "../context";
import { href, linkProps, navigate, useRoute } from "../router";
import { Markdown } from "../components/Markdown";
import { RunsTable, varyingParams } from "../components/bits";
import { Icon } from "../components/Icon";

const STATUSES: TaskStatus[] = ["todo", "doing", "blocked", "done", "dropped"];
const NEXT: Record<TaskStatus, TaskStatus> = { todo: "doing", doing: "done", done: "todo", blocked: "doing", dropped: "todo" };

interface PlanInfo {
  slug: string; title: string; status: string; parent: string | null; depth: number; number?: string; summary?: string;
  todo: number; doing: number; done: number; blocked: number; dropped: number;
}

function loadSet(key: string): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(key) ?? "[]")); } catch { return new Set(); }
}

export function Plans({ slug, focus }: { slug: string | null; focus: string | null }) {
  const { project } = useApp();
  const route = useRoute();
  const view = (route.query.get("view") as "tasks" | "doc" | "edit" | null) ?? "tasks";
  const plans = useApi<PlanInfo[]>(`/api/p/${project.id}/plans`, { poll: 5000 });
  const tasks = useApi<Task[]>(`/api/p/${project.id}/tasks`, { poll: 4000 });
  const docSlug = slug ?? "main";
  const plan = useApi<any>(view === "tasks" ? null : `/api/p/${project.id}/plans/${docSlug}`);
  const reloadAll = () => Promise.all([tasks.reload(), plans.reload()]).then(() => undefined);
  const setView = (v: "tasks" | "doc" | "edit", s: string = docSlug) =>
    navigate(`${href(project.id, "plans", s === "main" && v === "tasks" ? undefined : s)}${v === "tasks" ? "" : `?view=${v}`}`);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Plans</h1>
        {view !== "tasks" && plans.data && (
          <select className="input" style={{ width: "auto" }} value={docSlug} onChange={(e) => setView(view, e.target.value)}>
            {plans.data.map((p) => <option key={p.slug} value={p.slug}>{"  ".repeat(p.depth)}{p.number ? `${p.number} ` : ""}{p.title}</option>)}
          </select>
        )}
        {view !== "tasks" && plan.data && <span className="sub mono">docs/{plan.data.path}</span>}
        <span className="spacer" />
        <div className="tabs" style={{ margin: 0, border: 0 }}>
          {(["tasks", "doc", "edit"] as const).map((m) => (
            <button key={m} className={view === m ? "active" : ""} onClick={() => setView(m)}>
              {m === "tasks" ? "Tasks" : m === "doc" ? "Document" : "Edit"}
            </button>
          ))}
        </div>
      </div>

      {view === "tasks" && (tasks.error || plans.error) && <div className="error-box">{tasks.error || plans.error}</div>}
      {view === "tasks" && plans.data && tasks.data && (
        <PlanOutline plans={plans.data} tasks={tasks.data} focusPlan={slug} focus={focus} reload={reloadAll}
          openDoc={(s) => setView("doc", s)} />
      )}
      {view !== "tasks" && plan.error && <div className="error-box">{plan.error}</div>}
      {view === "doc" && plan.data && (
        <div className="card"><div className="card-body" style={{ padding: "20px 28px" }}>
          <Markdown pid={project.id} source={plan.data.markdown.replace(/^---\n[\s\S]*?\n---\n/, "")} docPath={plan.data.path} />
        </div></div>
      )}
      {view === "edit" && plan.data && (
        <PlanEditor key={docSlug} path={plan.data.path} initial={plan.data.markdown} onSaved={() => { reloadAll(); setView("doc"); }} />
      )}
    </div>
  );
}

function PlanOutline({ plans, tasks: loaded, focusPlan, focus, reload, openDoc }: {
  plans: PlanInfo[]; tasks: Task[]; focusPlan: string | null; focus: string | null; reload: () => Promise<void>;
  openDoc: (slug: string) => void;
}) {
  const { project, toast } = useApp();
  const storeKey = `dsd.plans.collapsed.${project.id}`;
  const [collapsed, setCollapsed] = useState<Set<string>>(() => loadSet(storeKey));
  const [showDone, setShowDone] = useState(true);
  const [open, setOpen] = useState<string | null>(focus);
  const [pending, setPending] = useState<Record<string, TaskStatus | "deleted">>({});
  useEffect(() => { try { localStorage.setItem(storeKey, JSON.stringify([...collapsed])); } catch { /* ignore */ } }, [collapsed, storeKey]);

  const tasks = loaded
    .filter((t) => !t.id || pending[t.id] !== "deleted")
    .map((t) => (t.id && pending[t.id] && pending[t.id] !== "deleted" ? { ...t, status: pending[t.id] as TaskStatus } : t));
  const settle = (ids: string[]) => setPending((p) => {
    const n = { ...p };
    ids.forEach((id) => delete n[id]);
    return n;
  });
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    tasks.forEach((t) => (c[t.status] = (c[t.status] ?? 0) + 1));
    return c;
  }, [tasks]);

  const byId = useMemo(() => new Map(loaded.filter((t) => t.id).map((t) => [t.id!, t])), [loaded]);
  const isUnder = (x: Task, id: string) => {
    let p = x.parent, d = 0;
    while (p && d < 8) { if (p === id) return true; p = byId.get(p)?.parent ?? null; d++; }
    return false;
  };
  const depthOf = (t: Task) => {
    let d = 0, p = t.parent;
    while (p && d < 6) { d++; p = byId.get(p)?.parent ?? null; }
    return d;
  };
  const ancestors = (slug: string) => {
    const out: string[] = [];
    let p = plans.find((x) => x.slug === slug)?.parent;
    while (p && out.length < 8) { out.push(p); p = plans.find((x) => x.slug === p)?.parent; }
    return out;
  };

  useEffect(() => {
    const target = focus ? byId.get(focus)?.plan : focusPlan;
    if (!target) return;
    setCollapsed((c) => {
      const n = new Set(c);
      [target, ...ancestors(target)].forEach((s) => n.delete(s));
      return n;
    });
    if (focus) setOpen(focus);
    requestAnimationFrame(() => document.getElementById(focus ? `task-${focus}` : `plan-${target}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [focus, focusPlan]);

  const hidden = (p: PlanInfo) => ancestors(p.slug).some((a) => collapsed.has(a));
  const toggle = (s: string) => setCollapsed((c) => { const n = new Set(c); n.has(s) ? n.delete(s) : n.add(s); return n; });

  const setStatus = async (t: Task, status: TaskStatus) => {
    if (!t.id) return;
    setPending((p) => ({ ...p, [t.id!]: status }));
    try {
      await patch(`/api/p/${project.id}/tasks/${t.id}`, { status });
      await reload();
    } catch (e: any) {
      toast(`Couldn't update ${t.id}: ${e.message || e}`);
    } finally {
      settle([t.id]);
    }
  };

  const remove = async (t: Task) => {
    if (!t.id) return;
    const ids = [t.id, ...tasks.filter((x) => isUnder(x, t.id!)).map((x) => x.id!)];
    setPending((p) => ({ ...p, ...Object.fromEntries(ids.map((id) => [id, "deleted" as const])) }));
    setOpen(null);
    try {
      const r = await del<{ deleted: string[] }>(`/api/p/${project.id}/tasks/${t.id}`);
      await reload();
      toast(`Deleted ${r.deleted.join(", ")}`);
    } catch (e: any) {
      toast(`Couldn't delete ${t.id}: ${e.message || e}`);
    } finally {
      settle(ids);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <span className="pill doing">{counts.doing ?? 0} doing</span>
        <span className="pill">{counts.todo ?? 0} todo</span>
        {counts.blocked ? <span className="pill blocked">{counts.blocked} blocked</span> : null}
        <span className="pill done">{counts.done ?? 0} done</span>
        <span className="spacer" />
        <button className="btn sm ghost" onClick={() => setCollapsed(new Set())}>Expand all</button>
        <button className="btn sm ghost" onClick={() => setCollapsed(new Set(plans.filter((p) => p.slug !== "main").map((p) => p.slug)))}>Collapse all</button>
        <label className="muted" style={{ fontWeight: 400, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> show done
        </label>
      </div>
      <div className="task-list" style={{ padding: 6 }}>
        {plans.filter((p) => !hidden(p)).map((p) => {
          const mine = tasks.filter((t) => t.plan === p.slug);
          const visible = mine.filter((t) => showDone || (t.status !== "done" && t.status !== "dropped") || t.id === open);
          const total = p.todo + p.doing + p.done + p.blocked;
          const isCollapsed = collapsed.has(p.slug);
          return (
            <div key={p.slug} className="plan-section" id={`plan-${p.slug}`}>
              <div className="plan-head" style={{ paddingLeft: 6 + p.depth * 18 }} onClick={() => toggle(p.slug)}>
                <span className="chev">{isCollapsed ? "▸" : "▾"}</span>
                {p.number ? <span className="plan-num mono">{p.number}</span> : null}
                <b className="plan-title">{p.slug === "main" ? "★ " : ""}{p.title}</b>
                {p.status && p.status !== "active" && <span className={`pill ${p.status === "agreed" || p.status === "done" ? "done" : p.status === "in progress" ? "doing" : ""}`}>{p.status}</span>}
                <span className="muted mono" style={{ fontSize: 11.5 }}>{p.done}/{total}</span>
                <span className="spacer" />
                <button className="btn sm ghost" onClick={(e) => { e.stopPropagation(); openDoc(p.slug); }}>Document</button>
              </div>
              {p.summary && <div className="plan-summary" style={{ paddingLeft: 30 + p.depth * 18 }}>{p.summary}</div>}
              {!isCollapsed && (
                <div style={{ paddingLeft: p.depth * 18 }}>
                  {visible.map((t) => (
                    <div key={t.id ?? t.title} id={t.id ? `task-${t.id}` : undefined}>
                      <div className={`task-row ${t.status} ${open === t.id ? "open" : ""}`} style={{ paddingLeft: 24 + depthOf(t) * 22 }}
                        onClick={() => setOpen(open === t.id ? null : t.id)}>
                        <button className={`status-btn ${t.status}`} title={`${t.status} → click for ${NEXT[t.status]}`}
                          onClick={(e) => { e.stopPropagation(); setStatus(t, NEXT[t.status]); }} />
                        <span className="id">{t.id ?? "—"}</span>
                        <span className="title">
                          {t.title}{" "}
                          {t.tags.map((g) => <span key={g} className="tag">#{g} </span>)}
                          {Object.entries(t.attrs).map(([k, v]) => <span key={k} className="attr">@{k}:{v} </span>)}
                        </span>
                        <span className="muted" style={{ fontSize: 11.5 }}>{t.notes.length ? `${t.notes.length} note${t.notes.length > 1 ? "s" : ""}` : ""}</span>
                      </div>
                      {open === t.id && t.id && (
                        <TaskDetail task={t} onChange={reload} setStatus={(s) => setStatus(t, s)} onDelete={() => remove(t)}
                          subtasks={tasks.filter((x) => isUnder(x, t.id!)).length} />
                      )}
                    </div>
                  ))}
                  {mine.length === 0 && <div className="muted" style={{ padding: "4px 0 4px 34px", fontSize: 12.5 }}>No tasks yet.</div>}
                  <AddRow slug={p.slug} onAdded={reload} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AddRow({ slug, onAdded }: { slug: string; onAdded: () => Promise<void> }) {
  const { project, toast } = useApp();
  const [mode, setMode] = useState<"idle" | "task" | "plan">("idle");
  const [text, setText] = useState("");
  const close = () => { setMode("idle"); setText(""); };
  const submit = async () => {
    const raw = text.trim();
    if (!raw) return;
    try {
      if (mode === "task") {
        const tags = Array.from(raw.matchAll(/(?:^|\s)#([\w\-/]+)/g)).map((m) => m[1]);
        const attrs = Object.fromEntries(Array.from(raw.matchAll(/(?:^|\s)@([\w-]+):(\S+)/g)).map((m) => [m[1], m[2]]));
        const clean = raw.replace(/(?:^|\s)#[\w\-/]+/g, "").replace(/(?:^|\s)@[\w-]+:\S+/g, "").trim();
        await post(`/api/p/${project.id}/tasks`, { title: clean, plan: slug, tags, attrs });
        setText("");
      } else {
        const s = raw.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, "");
        await post(`/api/p/${project.id}/plans`, { slug: s, title: raw, parent: slug });
        close();
      }
      await onAdded();
    } catch (e: any) {
      toast(`Couldn't add: ${e.message || e}`);
    }
  };
  if (mode === "idle") {
    return (
      <div style={{ display: "flex", gap: 4, padding: "2px 0 6px 30px" }}>
        <button className="btn sm ghost" onClick={() => setMode("task")}>+ Task</button>
        <button className="btn sm ghost" onClick={() => setMode("plan")}>+ Sub-plan</button>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 6, padding: "2px 0 8px 34px" }}>
      <input className="input" style={{ flex: 1 }} autoFocus value={text} onChange={(e) => setText(e.target.value)}
        placeholder={mode === "task" ? "Add a task…  (#tag @benchmark:name)" : "Sub-plan title"}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") close(); }} />
      <button className="btn sm" onClick={submit} disabled={!text.trim()}>{mode === "task" ? "Add" : "Create"}</button>
      <button className="btn sm ghost" onClick={close}>Done</button>
    </div>
  );
}

function PlanEditor({ path, initial, onSaved }: { path: string; initial: string; onSaved: () => void }) {
  const { project, toast } = useApp();
  const [text, setText] = useState(initial);
  const save = async () => {
    await put(`/api/p/${project.id}/docs/file`, { path, content: text });
    toast("Plan saved");
    onSaved();
  };
  return (
    <div className="stack">
      <textarea className="input" style={{ minHeight: "60vh" }} value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } }} />
      <div className="toolbar">
        <button className="btn primary" onClick={save}>Save <span className="kbd" style={{ color: "inherit", borderColor: "rgb(255 255 255 / .4)" }}>⌘S</span></button>
        <span className="muted">Task syntax: <code>- [ ] T-12 Title #tag @key:value</code> · markers [ ] [/] [x] [!] [-]</span>
      </div>
    </div>
  );
}

function TaskDetail({ task, onChange, setStatus, onDelete, subtasks }: {
  task: Task; onChange: () => Promise<void>; setStatus: (s: TaskStatus) => void; onDelete: () => void; subtasks: number;
}) {
  const { project, sendToAgent, toast } = useApp();
  const detail = useApi<any>(`/api/p/${project.id}/tasks/${task.id}`, { poll: 8000 });
  const [note, setNote] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const addNote = async () => {
    if (!note.trim()) return;
    try {
      await patch(`/api/p/${project.id}/tasks/${task.id}`, { note });
      setNote("");
      await onChange();
    } catch (e: any) {
      toast(`Couldn't add the note: ${e.message || e}`);
    }
  };
  const runs = detail.data?.runs ?? [];
  const metricKeys = Array.from(new Set(runs.flatMap((r: any) => Object.keys(r.metrics)))).slice(0, 3) as string[];
  return (
    <div className="task-detail">
      <div className="status-menu">
        {STATUSES.map((s) => (
          <button key={s} className={`btn sm ${task.status === s ? "primary" : ""}`} onClick={() => setStatus(s)}>{s}</button>
        ))}
        <span className="spacer" />
        <button className="btn sm" title="Starts Claude in this task's own worktree (branch dsd/<task>), or reuses it"
          onClick={() => sendToAgent(`/dsd-develop ${task.id}`, { session: { mode: "new", task: task.id!, task_title: task.title } })}>
          Work on this in a worktree
        </button>
        {task.tags.includes("exp") || task.attrs.benchmark ? (
          <button className="btn sm" onClick={() => sendToAgent(`/dsd-run-experiment for ${task.id}${task.attrs.benchmark ? ` on benchmark ${task.attrs.benchmark}` : ""}: `)}>Run experiment</button>
        ) : null}
        {confirmDelete ? (
          <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <span className="muted" style={{ fontSize: 12 }}>
              Delete {task.id}{subtasks ? ` and its ${subtasks} subtask${subtasks > 1 ? "s" : ""}` : ""}? To keep the history, mark it dropped instead.
            </span>
            <button className="btn sm danger" onClick={onDelete}>Delete</button>
            <button className="btn sm ghost" onClick={() => setConfirmDelete(false)}>Cancel</button>
          </span>
        ) : (
          <button className="btn sm ghost danger" title="Delete this task, its notes and its subtasks from the plan"
            onClick={() => setConfirmDelete(true)}><Icon name="trash" /> Delete</button>
        )}
      </div>
      {task.notes.length > 0 && <div className="notes">{task.notes.join("\n")}</div>}
      <div style={{ display: "flex", gap: 6 }}>
        <input className="input" style={{ flex: 1 }} placeholder="Add a note (appended under the task in the plan)" value={note}
          onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addNote()} />
        <button className="btn sm" onClick={addNote}>Note</button>
      </div>
      {runs.length > 0 && (
        <div>
          <div className="section-label" style={{ padding: "0 0 4px" }}>Runs for {task.id}</div>
          <RunsTable pid={project.id} runs={runs} metricKeys={metricKeys} paramKeys={varyingParams(runs, 2)} compact />
        </div>
      )}
      {detail.data?.commits?.length > 0 && (
        <div>
          <div className="section-label" style={{ padding: "0 0 4px" }}>Commits</div>
          {detail.data.commits.map((c: any) => (
            <div key={c.short} className="mono" style={{ fontSize: 12 }}>
              <a {...linkProps(`${href(project.id, "changes")}?ref=${c.short}`)}>{c.short}</a> <span className="muted">{c.date}</span> {c.subject}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
