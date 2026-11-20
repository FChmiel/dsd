import { useEffect, useState } from "react";
import { api, fmtTime, post, projectPath, tildify, type Run, type Task } from "../api";
import { useApp } from "../context";
import { href, linkProps } from "../router";
import { RunsTable, varyingParams } from "../components/bits";
import { Icon } from "../components/Icon";

export function Overview({ data }: { data: any; reload: () => void }) {
  const { project, sendToAgent } = useApp();
  const [archiving, setArchiving] = useState(false);
  if (!data) return <div className="page"><div className="empty">Loading…</div></div>;
  const runs: Run[] = data.recent_runs;
  const metricKeys = Array.from(new Set(runs.flatMap((r) => Object.keys(r.metrics)))).slice(0, 3);
  const doing: Task[] = data.in_progress;
  const blocked: Task[] = data.blocked;

  return (
    <div className="page">
      <div className="page-head">
        <h1>{project.name}</h1>
        <span className="sub mono" title={`Docs, plans and runs: ${tildify(project.data_dir)}`}>{projectPath(project)}</span>
        <span className="spacer" />
        <button className="btn ghost danger" onClick={() => setArchiving((a) => !a)}
          title="Hide this project and remove its worktrees. Branches, docs and runs are kept; restore it from Home.">
          <Icon name="archive" /> Archive project
        </button>
        <button className="btn" onClick={() => sendToAgent("/dsd-develop")}>Next task with Claude</button>
        <button className="btn primary" onClick={() => sendToAgent("/dsd-plan ")}>Plan with Claude</button>
      </div>

      {archiving && <ArchivePanel pid={project.id} name={project.name} onCancel={() => setArchiving(false)} />}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-head">Plan <span className="spacer" />
          <a className="sub" {...linkProps(href(project.id, "plans"))}>Open plans →</a></div>
        <div className="card-body plan-overview">
          {data.plans.map((p: any) => {
            const total = p.todo + p.doing + p.done + p.blocked;
            const pct = (n: number) => `${total ? (n / total) * 100 : 0}%`;
            return (
              <a key={p.slug} className="plan-ov-row" style={{ paddingLeft: p.depth * 20 }} {...linkProps(href(project.id, "plans", p.slug))}>
                <span className="plan-num mono">{p.number || "★"}</span>
                <span className="plan-ov-main">
                  <span className="plan-ov-title">
                    <b>{p.title}</b>
                    {p.status && p.status !== "active" && <span className="pill">{p.status}</span>}
                  </span>
                  {p.summary && <span className="plan-ov-summary">{p.summary}</span>}
                </span>
                <span className="plan-ov-progress">
                  <span className="progress" aria-label={`${p.done} of ${total} done`}>
                    <span style={{ width: pct(p.done), background: "var(--ok)" }} />
                    <span style={{ width: pct(p.doing), background: "var(--doing)" }} />
                    <span style={{ width: pct(p.blocked), background: "var(--bad)" }} />
                  </span>
                  <span className="muted mono" style={{ fontSize: 11.5 }}>{p.done}/{total}</span>
                </span>
              </a>
            );
          })}
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="card-head">In progress <span className="sub">{doing.length}</span></div>
          {doing.length === 0 && blocked.length === 0 && <div className="empty">Nothing in progress. Start one from <a {...linkProps(href(project.id, "plans"))}>Plans</a>.</div>}
          <div className="task-list" style={{ padding: 6 }}>
            {[...doing, ...blocked].map((t) => (
              <a key={t.id} className={`task-row ${t.status}`} style={{ color: "inherit", textDecoration: "none" }}
                {...linkProps(`${href(project.id, "plans", t.plan)}?task=${t.id}`)}>
                <span className={`status-btn ${t.status}`} />
                <span className="id">{t.id}</span>
                <span className="title">{t.title}</span>
                <span className="muted" style={{ fontSize: 12 }}>{t.plan !== "main" ? t.plan : ""}</span>
              </a>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-head">Workspace</div>
          <div className="card-body">
            <dl className="kv">
              <dt>Uncommitted changes</dt>
              <dd><a {...linkProps(href(project.id, "changes"))}>{data.changes} file{data.changes === 1 ? "" : "s"}</a>
                {data.open_comments > 0 && <span className="pill running" style={{ marginLeft: 8 }}>{data.open_comments} open comments</span>}</dd>
              <dt>Benchmarks</dt>
              <dd>
                {data.benchmarks.length === 0 && <span className="muted">none yet</span>}
                {data.benchmarks.map((b: any, i: number) => (
                  <span key={b.name}>{i > 0 && ", "}<a {...linkProps(href(project.id, "benchmarks", b.name))}>{b.name}</a>
                    <span className="muted"> ({b.runs})</span></span>
                ))}
              </dd>
              <dt>Last run</dt>
              <dd>{runs[0] ? `${runs[0].name} · ${fmtTime(runs[0].created_at)}` : <span className="muted">no runs yet</span>}</dd>
            </dl>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">Recent runs <span className="spacer" /><a className="sub" {...linkProps(href(project.id, "runs"))}>All runs →</a></div>
        {runs.length === 0 ? (
          <div className="empty">
            No runs yet. Track one with <code>dsd exec -b my-bench -- python train.py</code> or <code>with dsd.run(...)</code>.
          </div>
        ) : (
          <RunsTable pid={project.id} runs={runs} metricKeys={metricKeys} paramKeys={varyingParams(runs, 2)} />
        )}
      </div>
    </div>
  );
}

interface ArchivePreview {
  remove: { name: string; branch: string | null; dirty: number }[];
  unlist: { name: string; branch: string | null }[];
  blockers: { name: string; dirty: number }[];
}

function ArchivePanel({ pid, name, onCancel }: { pid: string; name: string; onCancel: () => void }) {
  const [preview, setPreview] = useState<ArchivePreview | null>(null);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api<ArchivePreview>(`/api/p/${pid}/archive`).then(setPreview).catch((e) => setErr(e.message || String(e)));
  }, [pid]);
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      await post(`/api/p/${pid}/archive`, { force });
      window.location.assign("/");
    } catch (e: any) {
      setErr(e.message || String(e));
      setBusy(false);
    }
  };
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-head">Archive {name}</div>
      <div className="card-body stack" style={{ gap: 6 }}>
        {!preview && !err && <div className="muted">Checking worktrees…</div>}
        {preview && <>
          <div>The project disappears from dsd until you restore it from Home. Its docs, plans and runs are kept.</div>
          {preview.remove.map((w) => (
            <div key={w.name}>Remove worktree <b>{w.name}</b> <span className="muted">(branch {w.branch} is kept)</span>
              {w.dirty ? <span className="pill killed" style={{ marginLeft: 6 }}>{w.dirty} uncommitted</span> : null}</div>
          ))}
          {preview.unlist.map((w) => <div key={w.name}>Stop listing adopted worktree <b>{w.name}</b> <span className="muted">(not deleted)</span></div>)}
          {preview.remove.length + preview.unlist.length === 0 && <div className="muted">No worktrees to remove.</div>}
          {preview.blockers.length > 0 && (
            <label className="dim" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              Discard the uncommitted changes in {preview.blockers.map((b) => b.name).join(", ")}
            </label>
          )}
        </>}
        {err && <div className="error-box">{err}</div>}
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <button className="btn danger" disabled={!preview || busy || (preview.blockers.length > 0 && !force)} onClick={go}>
            <Icon name="archive" /> {busy ? "Archiving…" : "Archive project"}</button>
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
