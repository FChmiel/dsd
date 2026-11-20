import { fmtTime, projectPath, tildify, type Run, type Task } from "../api";
import { useApp } from "../context";
import { href, linkProps } from "../router";
import { RunsTable, varyingParams } from "../components/bits";

export function Overview({ data }: { data: any; reload: () => void }) {
  const { project, sendToAgent } = useApp();
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
        <button className="btn" onClick={() => sendToAgent("/dsd-develop")}>Next task with Claude</button>
        <button className="btn primary" onClick={() => sendToAgent("/dsd-plan ")}>Plan with Claude</button>
      </div>

      <div className="grid-3" style={{ marginBottom: 14 }}>
        {data.plans.map((p: any) => {
          const total = p.todo + p.doing + p.done + p.blocked;
          const pct = (n: number) => `${total ? (n / total) * 100 : 0}%`;
          return (
            <a key={p.slug} className="card" style={{ textDecoration: "none", color: "inherit" }} {...linkProps(href(project.id, "plans", p.slug))}>
              <div className="card-body">
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <b>{p.title}</b>{p.slug === "main" && <span className="pill">central</span>}
                </div>
                <div className="progress" style={{ margin: "10px 0 8px" }} aria-label={`${p.done} of ${total} done`}>
                  <span style={{ width: pct(p.done), background: "var(--ok)" }} />
                  <span style={{ width: pct(p.doing), background: "var(--doing)" }} />
                  <span style={{ width: pct(p.blocked), background: "var(--bad)" }} />
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {p.done}/{total} done · {p.doing} in progress{p.blocked ? ` · ${p.blocked} blocked` : ""}
                </div>
              </div>
            </a>
          );
        })}
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
