import { Fragment, useState } from "react";
import { duration, fmtNum, fmtTime, shortId, useApi } from "../api";
import { useApp } from "../context";
import { href, linkProps, navigate } from "../router";
import { StatusPill, TaskLink } from "../components/bits";
import { LineChart, SLOTS } from "../components/LineChart";

export function RunDetail({ rid, tab: tabParam }: { rid: string; tab: string | null }) {
  const { project, sendToAgent } = useApp();
  const run = useApi<any>(`/api/p/${project.id}/runs/${rid}`, { poll: 4000 });
  const [tab, setTabState] = useState<string>(tabParam || "overview");
  const setTab = (t: string) => { setTabState(t); navigate(`${href(project.id, "runs", rid)}?tab=${t}`, true); };

  if (run.error) return <div className="page"><div className="error-box">{run.error}</div></div>;
  const d = run.data;
  if (!d) return <div className="page"><div className="empty">Loading…</div></div>;

  const stepped = Object.entries(d.series as Record<string, [number, number][]>).filter(([, pts]) => pts.length > 1);
  const htmls = d.artifact_list.filter((a: any) => /\.html?$/i.test(a.path));

  return (
    <div className="page">
      <div className="page-head">
        <a className="muted" {...linkProps(href(project.id, "runs"))}>Runs</a><span className="muted">/</span>
        <h1>{d.name}</h1>
        <StatusPill status={d.status} />
        <span className="id">{d.id}</span>
        <span className="spacer" />
        <button className="btn" onClick={() => sendToAgent(
          `Look at dsd run ${d.id} (${d.name}${d.benchmark ? `, benchmark ${d.benchmark}` : ""}). Use the dsd MCP tools (run_get, bench_board, runs_compare) and tell me how it compares to the best previous run and what to try next.`)}>
          Ask Claude about this run
        </button>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-body">
          <dl className="kv" style={{ gridTemplateColumns: "max-content minmax(0,1fr) max-content minmax(0,1fr)" }}>
            <dt>benchmark</dt><dd>{d.benchmark ? <a {...linkProps(href(project.id, "benchmarks", d.benchmark))}>{d.benchmark}</a> : "—"}</dd>
            <dt>task</dt><dd>{d.task ? <TaskLink pid={project.id} id={d.task} /> : "—"}</dd>
            <dt>started</dt><dd title={d.created_at}>{fmtTime(d.created_at)}</dd>
            <dt>duration</dt><dd>{duration(d.created_at, d.ended_at)}{!d.ended_at && d.status === "running" ? " (running)" : ""}</dd>
            <dt>git</dt>
            <dd className="mono">{d.git?.sha ? d.git.sha.slice(0, 10) : "no commit"} {d.git?.branch ?? ""}
              {d.git?.dirty && <a style={{ marginLeft: 6 }} onClick={() => setTab("diff")} href="#">dirty ↗</a>}</dd>
            <dt>user</dt><dd>{d.user}{d.worktree && <span className="pill" style={{ marginLeft: 8 }}>⎇ {d.worktree}</span>}</dd>
            {d.command && <><dt>command</dt><dd className="mono" style={{ gridColumn: "span 3", fontSize: 12 }}>{d.command.join(" ")}</dd></>}
            {d.error && <><dt>error</dt><dd style={{ gridColumn: "span 3", color: "var(--bad)" }} className="mono">{d.error}</dd></>}
            {d.tags.length > 0 && <><dt>tags</dt><dd style={{ gridColumn: "span 3" }}>{d.tags.map((t: string) => <span key={t} className="tag">#{t} </span>)}</dd></>}
          </dl>
        </div>
      </div>

      <div className="tabs">
        {[["overview", "Overview"], ["charts", `Charts`, stepped.length], ["artifacts", "Artifacts", d.artifact_list.length],
          ["logs", "Logs"], ["diff", "Git diff"]].map(([k, label, n]) => (
          <button key={k as string} className={tab === k ? "active" : ""} onClick={() => setTab(k as string)}>
            {label}{n ? <span className="count">{n}</span> : null}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid-2">
          <div className="card">
            <div className="card-head">Metrics</div>
            {Object.keys(d.metric_stats).length === 0 ? <div className="empty">No metrics logged</div> : (
              <table className="data">
                <thead><tr><th>metric</th><th className="num">last</th><th className="num">min</th><th className="num">max</th><th className="num">n</th></tr></thead>
                <tbody>
                  {Object.entries(d.metric_stats).sort().map(([k, s]: any) => (
                    <tr key={k}><td className="mono">{k}</td><td className="num best">{fmtNum(s.last)}</td><td className="num">{fmtNum(s.min)}</td>
                      <td className="num">{fmtNum(s.max)}</td><td className="num muted">{s.n}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <div className="card-head">Params</div>
            {Object.keys(d.params).length === 0 ? <div className="empty">No params</div> : (
              <table className="data">
                <tbody>
                  {Object.entries(d.params).sort().map(([k, v]) => (
                    <tr key={k}><td className="mono">{k}</td><td className="num">{typeof v === "object" ? JSON.stringify(v) : fmtNum(v)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {stepped.length > 0 && (
            <div className="card" style={{ gridColumn: "1 / -1" }}>
              <div className="card-head">Curves</div>
              <div className="card-body grid-2">
                {stepped.slice(0, 4).map(([k, pts]) => (
                  <LineChart key={k} title={k} series={[{ name: k, color: SLOTS[0], points: pts }]} height={180} />
                ))}
              </div>
            </div>
          )}
          {htmls.length > 0 && (
            <div className="card" style={{ gridColumn: "1 / -1" }}>
              <div className="card-head">{htmls[0].path}<span className="sub">{htmls[0].description}</span><span className="spacer" />
                <a className="sub" href="#" onClick={(e) => { e.preventDefault(); setTab("artifacts"); }}>All artifacts →</a></div>
              <iframe src={`/api/p/${project.id}/runs/${d.id}/artifacts/${htmls[0].path}`} sandbox="allow-scripts allow-popups"
                style={{ width: "100%", height: 460, border: 0, background: "white", display: "block", borderRadius: "0 0 8px 8px" }} title={htmls[0].path} />
            </div>
          )}
          {Object.keys(d.info).length > 0 && (
            <div className="card">
              <div className="card-head">Info</div>
              <div className="card-body">
                <dl className="kv">{Object.entries(d.info).map(([k, v]) => (
                  <Fragment key={k}><dt className="mono">{k}</dt><dd className="mono" style={{ fontSize: 12 }}>{typeof v === "string" ? v : JSON.stringify(v)}</dd></Fragment>
                ))}</dl>
              </div>
            </div>
          )}
          {d.datasets.length > 0 && (
            <div className="card">
              <div className="card-head">Datasets</div>
              <div className="card-body stack" style={{ gap: 8 }}>
                {d.datasets.map((ds: any, i: number) => (
                  <dl className="kv" key={i}>
                    {Object.entries(ds).map(([k, v]) => (
                      <Fragment key={k}><dt>{k}</dt><dd className="mono" style={{ fontSize: 12 }}>
                        {typeof v === "string" && /^https?:\/\//.test(v) ? <a href={v} target="_blank" rel="noreferrer">{v}</a> : String(v)}</dd></Fragment>
                    ))}
                  </dl>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "charts" && (
        <div className="card"><div className="card-body grid-2">
          {stepped.length === 0 && <div className="empty">No stepped metrics. Log curves with <code>r.log({"{"}"loss": l{"}"}, step=epoch)</code>.</div>}
          {stepped.map(([k, pts]) => <LineChart key={k} title={k} series={[{ name: k, color: SLOTS[0], points: pts }]} height={220} />)}
        </div></div>
      )}

      {tab === "artifacts" && <Artifacts pid={project.id} rid={d.id} list={d.artifact_list} />}
      {tab === "logs" && <RunText pid={project.id} rid={d.id} field="stdout" empty="No captured output (only runs launched with dsd exec capture stdout)." />}
      {tab === "diff" && <RunText pid={project.id} rid={d.id} field="diff" empty="Working tree was clean when this run started." />}
    </div>
  );
}

function Artifacts({ pid, rid, list }: { pid: string; rid: string; list: any[] }) {
  const [sel, setSel] = useState<string | null>(list.find((a) => /\.html?$/i.test(a.path))?.path ?? list[0]?.path ?? null);
  if (!list.length) return <div className="card"><div className="empty">No artifacts. Add with <code>r.artifact(path)</code> or <code>r.html(name, html)</code>.</div></div>;
  const url = (p: string) => `/api/p/${pid}/runs/${rid}/artifacts/${p}`;
  const a = list.find((x) => x.path === sel);
  const isImg = a && /^image\//.test(a.mime);
  const isHtml = a && /\.html?$/i.test(a.path);
  return (
    <div className="card" style={{ display: "grid", gridTemplateColumns: "240px minmax(0,1fr)", minHeight: 520 }}>
      <div style={{ borderRight: "1px solid var(--border)", padding: 6 }}>
        {list.map((x) => (
          <button key={x.path} className={`tree-item ${x.path === sel ? "active" : ""}`} onClick={() => setSel(x.path)} title={x.description ?? x.path}>
            {x.path}<span className="spacer" /><span className="muted" style={{ fontSize: 11 }}>{(x.size / 1024).toFixed(1)}k</span>
          </button>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        {a && (
          <div className="doc-head" style={{ position: "static" }}>
            <span className="path">{a.path}</span><span className="muted">{a.description}</span><span className="spacer" />
            <a className="btn sm ghost" href={url(a.path)} target="_blank" rel="noreferrer">Open ↗</a>
          </div>
        )}
        {a && isHtml && <iframe src={url(a.path)} sandbox="allow-scripts allow-popups" style={{ flex: 1, border: 0, background: "white", minHeight: 480 }} title={a.path} />}
        {a && isImg && <div style={{ padding: 16 }}><img src={url(a.path)} alt={a.path} style={{ maxWidth: "100%" }} /></div>}
        {a && !isHtml && !isImg && <TextArtifact url={url(a.path)} />}
      </div>
    </div>
  );
}

function TextArtifact({ url }: { url: string }) {
  const { data } = useApi<string>(url);
  return <pre className="mono" style={{ margin: 0, padding: 16, whiteSpace: "pre-wrap", overflow: "auto", maxHeight: 600 }}>{typeof data === "string" ? data.slice(0, 200000) : data ? JSON.stringify(data, null, 2) : "…"}</pre>;
}

function RunText({ pid, rid, field, empty }: { pid: string; rid: string; field: "stdout" | "diff"; empty: string }) {
  const { data } = useApi<{ diff: string; stdout: string }>(`/api/p/${pid}/runs/${rid}/diff`);
  const text = data?.[field] ?? "";
  if (data && !text) return <div className="card"><div className="empty">{empty}</div></div>;
  return (
    <div className="card">
      <pre className="mono" style={{ margin: 0, padding: 14, whiteSpace: "pre-wrap", overflow: "auto", maxHeight: "70vh", fontSize: 12 }}>
        {field === "diff" ? text.split("\n").map((ln, i) => (
          <div key={i} style={{ color: ln.startsWith("+") && !ln.startsWith("+++") ? "var(--add-text)" : ln.startsWith("-") && !ln.startsWith("---") ? "var(--del-text)" : ln.startsWith("@@") ? "var(--accent-text)" : undefined }}>{ln || " "}</div>
        )) : text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")}
      </pre>
    </div>
  );
}
