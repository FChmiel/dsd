import { fmtNum, fmtTime, shortId, type Run } from "../api";
import { href, linkProps, navigate } from "../router";

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill ${status}`}>{status}</span>;
}

export function TaskLink({ pid, id }: { pid: string; id: string | null }) {
  if (!id) return null;
  return <a className="mono" {...linkProps(`${href(pid, "plans")}?task=${id}`)}>{id}</a>;
}

/** Param keys whose values differ across these runs (the interesting columns). */
export function varyingParams(runs: Run[], max = 4): string[] {
  const keys = new Set<string>();
  runs.forEach((r) => Object.keys(r.params).forEach((k) => keys.add(k)));
  const out: string[] = [];
  for (const k of keys) {
    const present = runs.filter((r) => r.params[k] !== undefined && r.params[k] !== null);
    const vals = new Set(present.map((r) => JSON.stringify(r.params[k])));
    if (vals.size > 1) out.push(k);
  }
  return out.slice(0, max);
}

export function RunsTable({ pid, runs, metricKeys, paramKeys, selected, onToggle, sort, onSort, compact }: {
  pid: string;
  runs: Run[];
  metricKeys: string[];
  paramKeys: string[];
  selected?: Set<string>;
  onToggle?: (id: string) => void;
  sort?: string | null;
  onSort?: (field: string) => void;
  compact?: boolean;
}) {
  const best: Record<string, number | undefined> = {};
  metricKeys.forEach((k) => {
    const vals = runs.map((r) => r.metrics[k]).filter((v) => typeof v === "number");
    if (vals.length > 1) best[k] = /loss|err|rmse|mae|mse|time|latency/i.test(k) ? Math.min(...vals) : Math.max(...vals);
  });
  const sortInd = (f: string) => (sort === f ? " ↑" : sort === `-${f}` ? " ↓" : "");
  const Th = ({ f, children, cls }: { f: string; children: React.ReactNode; cls?: string }) => (
    <th className={`${cls ?? ""} ${onSort ? "sortable" : ""}`} onClick={() => onSort?.(f)}>{children}{sortInd(f)}</th>
  );
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {onToggle && <th style={{ width: 28 }} />}
            <Th f="name">run</Th>
            <Th f="status">status</Th>
            {!compact && <Th f="benchmark">benchmark</Th>}
            {!compact && <Th f="task">task</Th>}
            {paramKeys.map((k) => <Th key={k} f={`params.${k}`} cls="num">{k}</Th>)}
            {metricKeys.map((k) => <Th key={k} f={`metrics.${k}`} cls="num metric-head">{k}</Th>)}
            <Th f="created_at" cls="right">created</Th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className={`clickable ${selected?.has(r.id) ? "selected" : ""}`}
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("input,a")) return;
                navigate(href(pid, "runs", r.id));
              }}>
              {onToggle && (
                <td><input type="checkbox" checked={selected?.has(r.id) ?? false} onChange={() => onToggle(r.id)} /></td>
              )}
              <td>
                <div style={{ fontWeight: 550 }} title={(r as any).info?.description ?? undefined}>{r.name}</div>
                {(r as any).info?.description && !compact && (
                  <div className="muted" style={{ fontSize: 11.5, maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {(r as any).info.description}
                  </div>
                )}
                <div className="id">{shortId(r.id)}{r.artifacts ? ` · ${r.artifacts} artifact${r.artifacts > 1 ? "s" : ""}` : ""}</div>
              </td>
              <td><StatusPill status={r.status} /></td>
              {!compact && <td>{r.benchmark && <a {...linkProps(href(pid, "benchmarks", r.benchmark))}>{r.benchmark}</a>}</td>}
              {!compact && <td><TaskLink pid={pid} id={r.task} /></td>}
              {paramKeys.map((k) => <td key={k} className="num">{fmtNum(r.params[k])}</td>)}
              {metricKeys.map((k) => (
                <td key={k} className={`num ${best[k] !== undefined && r.metrics[k] === best[k] ? "best" : ""}`}>{fmtNum(r.metrics[k])}</td>
              ))}
              <td className="right muted nowrap" title={r.created_at}>{fmtTime(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
