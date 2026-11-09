import { useMemo, useState } from "react";
import { qs, useApi, type Run } from "../api";
import { useApp } from "../context";
import { href, navigate } from "../router";
import { RunsTable, varyingParams } from "../components/bits";

function usePersisted<T>(key: string, init: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = sessionStorage.getItem(key); return s ? JSON.parse(s) : init; } catch { return init; }
  });
  return [v, (nv: T) => { setV(nv); try { sessionStorage.setItem(key, JSON.stringify(nv)); } catch { /* */ } }];
}

export function Runs() {
  const { project } = useApp();
  const [benchmark, setBenchmark] = usePersisted<string>("runs.bench", "");
  const [status, setStatus] = usePersisted<string>("runs.status", "");
  const [task, setTask] = usePersisted<string>("runs.task", "");
  const [where, setWhere] = usePersisted<string>("runs.where", "");
  const [sort, setSort] = usePersisted<string | null>("runs.sort", null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const benches = useApi<any[]>(`/api/p/${project.id}/benchmarks`);

  const url = `/api/p/${project.id}/runs${qs({
    benchmark, status, task, sort: sort ?? undefined,
    where: where.split(";").map((w) => w.trim()).filter(Boolean),
  })}`;
  const runs = useApi<Run[]>(url, { poll: 5000 });
  const data = runs.data ?? [];

  const metricKeys = useMemo(() => {
    const counts = new Map<string, number>();
    data.forEach((r) => Object.keys(r.metrics).forEach((k) => counts.set(k, (counts.get(k) ?? 0) + 1)));
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 6).map(([k]) => k).sort();
  }, [data]);
  const paramKeys = useMemo(() => varyingParams(data, 4), [data]);

  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const onSort = (f: string) => setSort(sort === `-${f}` ? f : sort === f ? null : `-${f}`);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Runs</h1>
        <span className="sub">{data.length} shown</span>
        <span className="spacer" />
        <button className="btn primary" disabled={selected.size < 2}
          onClick={() => navigate(`${href(project.id, "compare")}?ids=${Array.from(selected).join(",")}`)}>
          Compare {selected.size >= 2 ? `(${selected.size})` : ""}
        </button>
      </div>
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <select className="input" value={benchmark} onChange={(e) => setBenchmark(e.target.value)}>
          <option value="">All benchmarks</option>
          {(benches.data ?? []).map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
        </select>
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          {["running", "finished", "failed", "killed", "crashed"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <input className="input" style={{ width: 90 }} placeholder="Task" value={task} onChange={(e) => setTask(e.target.value)} />
        <input className="input mono" style={{ flex: 1, minWidth: 220, fontSize: 12 }} placeholder="Filter: metrics.auc>=0.8; params.model=xgb; name~base"
          value={where} onChange={(e) => setWhere(e.target.value)} />
        {(benchmark || status || task || where || sort) && (
          <button className="btn ghost" onClick={() => { setBenchmark(""); setStatus(""); setTask(""); setWhere(""); setSort(null); }}>Clear</button>
        )}
      </div>
      {runs.error && <div className="error-box" style={{ marginBottom: 12 }}>{runs.error}</div>}
      <div className="card">
        {runs.data && data.length === 0 ? (
          <div className="empty">
            No runs match. Track experiments with <code>dsd exec -b &lt;benchmark&gt; -- python train.py</code>,
            or in code: <code>with dsd.run("name", benchmark=…) as r: r.log(...)</code>
          </div>
        ) : (
          <RunsTable pid={project.id} runs={data} metricKeys={metricKeys} paramKeys={paramKeys}
            selected={selected} onToggle={toggle} sort={sort} onSort={onSort} />
        )}
      </div>
    </div>
  );
}
