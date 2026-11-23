import { useMemo, useState } from "react";
import { fmtNum, fmtTime, put, qs, shortId, useApi } from "../api";
import { useApp } from "../context";
import { href, linkProps, navigate } from "../router";

export function Benchmarks({ name }: { name: string | null }) {
  const { project } = useApp();
  const list = useApi<any[]>(`/api/p/${project.id}/benchmarks`, { poll: 10000 });
  const current = name ?? list.data?.[0]?.name ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Benchmarks</h1>
        <span className="sub">named groups of comparable runs</span>
      </div>
      {list.data && list.data.length === 0 && (
        <div className="card"><div className="empty">
          No benchmarks yet. Tag runs with a benchmark: <code>dsd exec -b churn-v1 -- python train.py</code> or{" "}
          <code>dsd.run("xgb", benchmark="churn-v1")</code>.
        </div></div>
      )}
      {list.data && list.data.length > 0 && (
        <>
          <div className="tabs">
            {list.data.map((b) => (
              <button key={b.name} className={b.name === current ? "active" : ""} onClick={() => navigate(href(project.id, "benchmarks", b.name))}>
                {b.name}<span className="count">{b.runs}</span>
              </button>
            ))}
          </div>
          {current && <Board key={current} name={current} onSpec={list.reload} />}
        </>
      )}
    </div>
  );
}

function Board({ name, onSpec }: { name: string; onSpec: () => void }) {
  const { project, sendToAgent } = useApp();
  const [groupBy, setGroupBy] = useState<string>("");
  const [allStatus, setAllStatus] = useState(false);
  const [order, setOrderState] = useState<"created" | "rank">(() => {
    try { return localStorage.getItem("dsd.bench.order") === "rank" ? "rank" : "created"; } catch { return "created"; }
  });
  const setOrder = (o: "created" | "rank") => {
    setOrderState(o);
    try { localStorage.setItem("dsd.bench.order", o); } catch { /* ignore */ }
  };
  const board = useApi<any>(`/api/p/${project.id}/benchmarks/${encodeURIComponent(name)}${qs({ group_by: groupBy, all_status: allStatus || undefined })}`, { poll: 8000 });
  const flat = useApi<any>(`/api/p/${project.id}/benchmarks/${encodeURIComponent(name)}${qs({ all_status: true })}`);
  const b = board.data;

  const groupOptions = useMemo(() => {
    const keys = new Set<string>();
    (flat.data?.rows ?? []).forEach((r: any) => Object.keys(r.params ?? {}).forEach((k) => keys.add(k)));
    return ["name", ...Array.from(keys).sort().map((k) => `params.${k}`)];
  }, [flat.data]);

  const setSpec = async (primary: string, direction: string) => {
    await put(`/api/p/${project.id}/benchmarks/${encodeURIComponent(name)}`, { primary: primary || null, direction });
    board.reload();
    onSpec();
  };

  if (board.error) return <div className="error-box">{board.error}</div>;
  if (!b) return <div className="empty">Loading…</div>;
  const primary = b.spec.primary as string | undefined;
  const dir = (b.spec.direction as string) ?? "max";
  const keys: string[] = b.metrics.slice(0, 8);
  const byRank = order === "rank" && !!primary;
  const rows: any[] = b.grouped || byRank ? b.rows
    : [...b.rows].sort((x: any, y: any) => (Date.parse(y.run.created_at ?? "") || 0) - (Date.parse(x.run.created_at ?? "") || 0));
  const orderTitle = (target: "rank" | "created") => (target === "rank" ? "Sort by rank" : "Sort newest first");

  return (
    <div className="stack">
      <div className="toolbar">
        <label className="muted">Rank by</label>
        <select className="input" value={primary ?? ""} onChange={(e) => setSpec(e.target.value, dir)}>
          <option value="">(no primary metric)</option>
          {b.metrics.map((m: string) => <option key={m}>{m}</option>)}
        </select>
        <select className="input" value={dir} onChange={(e) => setSpec(primary ?? "", e.target.value)} disabled={!primary}>
          <option value="max">higher is better</option>
          <option value="min">lower is better</option>
        </select>
        <span style={{ width: 12 }} />
        <label className="muted">Group by</label>
        <input className="input mono" style={{ width: 240, fontSize: 12 }} list="dsd-groupby" placeholder="(each run) e.g. params.model,params.lr"
          defaultValue={groupBy} onKeyDown={(e) => e.key === "Enter" && setGroupBy((e.target as HTMLInputElement).value.trim())}
          onBlur={(e) => setGroupBy(e.target.value.trim())} />
        <datalist id="dsd-groupby">
          {groupOptions.map((g) => <option key={g} value={g} />)}
        </datalist>
        <label className="muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={allStatus} onChange={(e) => setAllStatus(e.target.checked)} /> include unfinished
        </label>
        <span className="spacer" />
        <button className="btn" onClick={() => sendToAgent(`/dsd-report leaderboard and analysis for benchmark ${name}`)}>Report with Claude</button>
      </div>

      <div className="card">
        {b.rows.length === 0 ? <div className="empty">No finished runs in this benchmark yet.</div> : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th className={`num ${!b.grouped && primary ? "sortable" : ""}`} style={{ width: 36 }}
                    title={!b.grouped && primary ? orderTitle("rank") : undefined}
                    onClick={() => !b.grouped && primary && setOrder("rank")}>#{byRank && !b.grouped ? " ↓" : ""}</th>
                  <th>{b.grouped ? b.group_by : "run"}</th>
                  {b.grouped && <th className="num">n</th>}
                  {!b.grouped && <th>task</th>}
                  {keys.map((k) => (
                    <th key={k} className="num metric-head" style={k === primary ? { color: "var(--text)" } : undefined}>
                      {k}{k === primary ? (dir === "max" ? " ↑" : " ↓") : ""}
                    </th>
                  ))}
                  {!b.grouped && <th className="right sortable" title={orderTitle("created")} onClick={() => setOrder("created")}>created{!byRank ? " ↓" : ""}</th>}
                </tr>
              </thead>
              <tbody>
                {b.grouped ? b.rows.map((row: any) => (
                  <tr key={row.group} className="clickable" onClick={() => navigate(`${href(project.id, "compare")}?ids=${row.run_ids.slice(0, 8).join(",")}`)}>
                    <td className="num muted">{row.rank ?? ""}</td>
                    <td><b>{row.group}</b>{row.best_run && <span className="id"> · best {shortId(row.best_run)}</span>}</td>
                    <td className="num">{row.n}</td>
                    {keys.map((k) => {
                      const s = row.stats[k];
                      return (
                        <td key={k} className={`num ${k === primary && row.rank === 1 ? "best" : ""}`}>
                          {s.mean === null ? "—" : <>{fmtNum(s.mean)}{s.n > 1 && <span className="muted"> ± {fmtNum(s.std)}</span>}</>}
                        </td>
                      );
                    })}
                  </tr>
                )) : rows.map((row: any) => (
                  <tr key={row.run.id} className="clickable" onClick={() => navigate(href(project.id, "runs", row.run.id))}>
                    <td className="num muted">{row.rank ?? ""}</td>
                    <td><b>{row.run.name}</b> <span className="id">{shortId(row.run.id)}</span></td>
                    <td>{row.run.task && <a className="mono" {...linkProps(`${href(project.id, "plans")}?task=${row.run.task}`)}>{row.run.task}</a>}</td>
                    {keys.map((k) => (
                      <td key={k} className={`num ${k === primary && row.rank === 1 ? "best" : ""}`}>{fmtNum(row.metrics[k])}</td>
                    ))}
                    <td className="right muted nowrap">{fmtTime(row.run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {b.grouped && <div className="muted" style={{ fontSize: 12 }}>Groups show mean ± std across runs (e.g. seeds). Click a group to compare its runs.</div>}
    </div>
  );
}
