import { useEffect, useMemo, useState } from "react";
import { api, patch, post, put, useApi, type Task, type TaskStatus } from "../api";
import { useApp } from "../context";
import { href, linkProps, navigate } from "../router";
import { Markdown } from "../components/Markdown";
import { RunsTable, varyingParams } from "../components/bits";

const STATUSES: TaskStatus[] = ["todo", "doing", "blocked", "done", "dropped"];
const NEXT: Record<TaskStatus, TaskStatus> = { todo: "doing", doing: "done", done: "todo", blocked: "doing", dropped: "todo" };

export function Plans({ slug, focus }: { slug: string; focus: string | null }) {
  const { project } = useApp();
  const plans = useApi<any[]>(`/api/p/${project.id}/plans`, { poll: 5000 });
  const plan = useApi<any>(`/api/p/${project.id}/plans/${slug}`, { poll: 4000 });
  const [mode, setMode] = useState<"tasks" | "doc" | "edit">("tasks");
  const [showDone, setShowDone] = useState(true);
  const [newPlan, setNewPlan] = useState<string | null>(null);

  const reloadAll = () => { plan.reload(); plans.reload(); };

  return (
    <div className="page">
      <div className="page-head">
        <h1>{plan.data?.title ?? slug}</h1>
        {slug === "main" && <span className="pill">central plan</span>}
        <span className="sub mono">docs/{plan.data?.path}</span>
        <span className="spacer" />
        <div className="tabs" style={{ margin: 0, border: 0 }}>
          {(["tasks", "doc", "edit"] as const).map((m) => (
            <button key={m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>
              {m === "tasks" ? "Tasks" : m === "doc" ? "Document" : "Edit"}
            </button>
          ))}
        </div>
      </div>

      <div className="tabs">
        {(plans.data ?? []).map((p) => (
          <button key={p.slug} className={p.slug === slug ? "active" : ""} onClick={() => navigate(href(project.id, "plans", p.slug))}>
            {p.slug === "main" ? "★ " : ""}{p.title}
            <span className="count">{p.done}/{p.todo + p.doing + p.done + p.blocked}</span>
          </button>
        ))}
        {newPlan === null ? (
          <button onClick={() => setNewPlan("")} title="New sub-plan">+ Sub-plan</button>
        ) : (
          <form style={{ display: "flex", gap: 6, alignItems: "center", padding: "2px 6px" }} onSubmit={async (e) => {
            e.preventDefault();
            const s = newPlan.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, "");
            if (!s) return;
            await post(`/api/p/${project.id}/plans`, { slug: s, title: newPlan.trim() });
            setNewPlan(null);
            plans.reload();
            navigate(href(project.id, "plans", s));
          }}>
            <input className="input" autoFocus placeholder="Sub-plan title" value={newPlan} onChange={(e) => setNewPlan(e.target.value)}
              onKeyDown={(e) => e.key === "Escape" && setNewPlan(null)} />
            <button className="btn sm primary">Create</button>
          </form>
        )}
      </div>

      {plan.error && <div className="error-box">{plan.error}</div>}
      {plan.data && mode === "tasks" && (
        <TaskBoard tasks={plan.data.tasks} slug={slug} focus={focus} showDone={showDone} setShowDone={setShowDone} reload={reloadAll} />
      )}
      {plan.data && mode === "doc" && (
        <div className="card"><div className="card-body" style={{ padding: "20px 28px" }}>
          <Markdown pid={project.id} source={plan.data.markdown.replace(/^---\n[\s\S]*?\n---\n/, "")} docPath={plan.data.path} />
        </div></div>
      )}
      {plan.data && mode === "edit" && <PlanEditor path={plan.data.path} initial={plan.data.markdown} onSaved={() => { reloadAll(); setMode("tasks"); }} />}
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

function TaskBoard({ tasks, slug, focus, showDone, setShowDone, reload }: {
  tasks: Task[]; slug: string; focus: string | null; showDone: boolean; setShowDone: (b: boolean) => void; reload: () => void;
}) {
  const { project } = useApp();
  const [open, setOpen] = useState<string | null>(focus);
  const [title, setTitle] = useState("");
  useEffect(() => { if (focus) setOpen(focus); }, [focus]);

  const visible = tasks.filter((t) => showDone || (t.status !== "done" && t.status !== "dropped") || t.id === open);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    tasks.forEach((t) => (c[t.status] = (c[t.status] ?? 0) + 1));
    return c;
  }, [tasks]);
  const depth = (t: Task) => {
    let d = 0, p = t.parent;
    while (p && d < 6) { d++; p = tasks.find((x) => x.id === p)?.parent ?? null; }
    return d;
  };

  const setStatus = async (t: Task, status: TaskStatus) => {
    await patch(`/api/p/${project.id}/tasks/${t.id}`, { status });
    reload();
  };

  const add = async () => {
    const raw = title.trim();
    if (!raw) return;
    const tags = Array.from(raw.matchAll(/(?:^|\s)#([\w\-/]+)/g)).map((m) => m[1]);
    const attrs = Object.fromEntries(Array.from(raw.matchAll(/(?:^|\s)@([\w-]+):(\S+)/g)).map((m) => [m[1], m[2]]));
    const clean = raw.replace(/(?:^|\s)#[\w\-/]+/g, "").replace(/(?:^|\s)@[\w-]+:\S+/g, "").trim();
    await post(`/api/p/${project.id}/tasks`, { title: clean, plan: slug, tags, attrs });
    setTitle("");
    reload();
  };

  return (
    <div className="card">
      <div className="card-head">
        <span className="pill doing">{counts.doing ?? 0} doing</span>
        <span className="pill">{counts.todo ?? 0} todo</span>
        {counts.blocked ? <span className="pill blocked">{counts.blocked} blocked</span> : null}
        <span className="pill done">{counts.done ?? 0} done</span>
        <span className="spacer" />
        <label className="muted" style={{ fontWeight: 400, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> show done
        </label>
      </div>
      <div className="task-list" style={{ padding: 6 }}>
        {visible.length === 0 && <div className="empty">No tasks yet. Add one below, or ask Claude to <code>/dsd-plan</code>.</div>}
        {visible.map((t) => (
          <div key={t.id ?? t.title}>
            <div className={`task-row ${t.status} ${open === t.id ? "open" : ""}`} style={{ paddingLeft: 10 + depth(t) * 22 }}
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
            {open === t.id && t.id && <TaskDetail task={t} onChange={reload} setStatus={(s) => setStatus(t, s)} />}
          </div>
        ))}
      </div>
      <div className="add-row" style={{ borderTop: "1px solid var(--border)" }}>
        <input className="input" placeholder="Add a task…  (#tag @benchmark:name)" value={title}
          onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn" onClick={add} disabled={!title.trim()}>Add</button>
      </div>
    </div>
  );
}

function TaskDetail({ task, onChange, setStatus }: { task: Task; onChange: () => void; setStatus: (s: TaskStatus) => void }) {
  const { project, sendToAgent } = useApp();
  const detail = useApi<any>(`/api/p/${project.id}/tasks/${task.id}`, { poll: 8000 });
  const [note, setNote] = useState("");
  const addNote = async () => {
    if (!note.trim()) return;
    await patch(`/api/p/${project.id}/tasks/${task.id}`, { note });
    setNote("");
    onChange();
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
