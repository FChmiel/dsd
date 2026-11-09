import { useState } from "react";
import { fmtNum, shortId, useApi } from "../api";
import { useApp } from "../context";
import { href, linkProps } from "../router";
import { StatusPill } from "../components/bits";
import { LineChart, SLOTS } from "../components/LineChart";

const LOWER_BETTER = /loss|err|rmse|mae|mse|time|latency/i;

export function Compare({ ids }: { ids: string[] }) {
  const { project, sendToAgent } = useApp();
  const shown = ids.slice(0, 8); // categorical cap: 8 fixed slots, never cycled
  const cmp = useApi<any>(shown.length ? `/api/p/${project.id}/compare?ids=${shown.join(",")}` : null);
  const series = useApi<Record<string, Record<string, [number, number][]>>>(
    shown.length ? `/api/p/${project.id}/series?ids=${shown.join(",")}` : null);
  const [allParams, setAllParams] = useState(false);

  if (shown.length < 2) return <div className="page"><div className="empty">Select at least two runs on the Runs page to compare.</div></div>;
  if (cmp.error) return <div className="page"><div className="error-box">{cmp.error}</div></div>;
  const c = cmp.data;
  if (!c) return <div className="page"><div className="empty">Loading…</div></div>;

  const runs: any[] = c.runs;
  const color = (i: number) => SLOTS[i];
  const steppedKeys = new Set<string>();
  Object.values(series.data ?? {}).forEach((m) => Object.entries(m).forEach(([k, pts]) => pts.length > 1 && steppedKeys.add(k)));

  return (
    <div className="page">
      <div className="page-head">
        <a className="muted" {...linkProps(href(project.id, "runs"))}>Runs</a><span className="muted">/</span>
        <h1>Compare {runs.length} runs</h1>
        {ids.length > 8 && <span className="pill killed">showing first 8 of {ids.length}</span>}
        <span className="spacer" />
        <button className="btn" onClick={() => sendToAgent(
          `Compare dsd runs ${runs.map((r) => r.id).join(", ")} with the runs_compare MCP tool. Explain which changes drove the metric differences and suggest the next experiment.`)}>
          Ask Claude to explain
        </button>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th />
                {runs.map((r, i) => (
                  <th key={r.id} className="num">
                    <span style={{ display: "inline-block", width: 12, height: 2, background: color(i), verticalAlign: "middle", marginRight: 6 }} />
                    <a {...linkProps(href(project.id, "runs", r.id))} style={{ color: "var(--text)" }}>{r.name}</a>
                    <div className="id">{shortId(r.id)}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr><td className="muted">status</td>{runs.map((r) => <td key={r.id} className="num"><StatusPill status={r.status} /></td>)}</tr>
              <tr><td colSpan={runs.length + 1} className="section-label">Metrics</td></tr>
              {c.metrics.map((m: any) => {
                const nums = m.values.filter((v: any) => typeof v === "number");
                const best = nums.length > 1 ? (LOWER_BETTER.test(m.key) ? Math.min(...nums) : Math.max(...nums)) : undefined;
                return (
                  <tr key={m.key}>
                    <td className="mono">{m.key}</td>
                    {m.values.map((v: any, i: number) => <td key={i} className={`num ${v === best ? "best" : ""}`}>{fmtNum(v)}{v === best ? " ★" : ""}</td>)}
                  </tr>
                );
              })}
              <tr>
                <td colSpan={runs.length + 1} className="section-label">
                  Params {!allParams && <span style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>(differing only)</span>}
                  <button className="btn sm ghost" style={{ marginLeft: 8 }} onClick={() => setAllParams((a) => !a)}>{allParams ? "Only differing" : "Show all"}</button>
                </td>
              </tr>
              {c.params.filter((p: any) => allParams || p.differs).map((p: any) => (
                <tr key={p.key}>
                  <td className="mono">{p.key}</td>
                  {p.values.map((v: any, i: number) => (
                    <td key={i} className={`num ${p.differs ? "differs" : "muted"}`}>{typeof v === "object" && v !== null ? JSON.stringify(v) : fmtNum(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {steppedKeys.size > 0 && (
        <div className="card">
          <div className="card-head">Curves</div>
          <div className="card-body grid-2">
            {Array.from(steppedKeys).sort().map((k) => (
              <LineChart key={k} title={k} height={220}
                series={runs.map((r, i) => ({ name: r.name, color: color(i), points: series.data?.[r.id]?.[k] ?? [] })).filter((s) => s.points.length)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
