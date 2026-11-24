import { useMemo } from "react";
import { useApi } from "../api";
import { href, linkProps } from "../router";

interface Day { tokens: number; output: number; messages: number; sessions: number }
interface Usage {
  from: string;
  to: string;
  recent_days: number;
  days: Record<string, Day>;
  totals: { tokens: number; output: number; cache_read: number; messages: number; sessions: number };
  models: { model: string; tokens: number; messages: number }[];
  projects: { project: string; project_id: string | null; tokens: number }[];
}

const CELL = 11;
const GAP = 3;
const DAY_MS = 86400000;

export function fmtTokens(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return String(n);
}

function modelName(id: string): string {
  const m = id.replace(/^claude-/, "").replace(/-\d{8}$/, "").match(/^([a-z]+)-(\d+)(?:-(\d+))?$/);
  if (!m) return id;
  return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? `.${m[3]}` : ""}`;
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const label = (s: string) => parse(s).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

function levels(values: number[]): number[] {
  const nz = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (!nz.length) return [1, 1, 1];
  const q = (p: number) => nz[Math.min(nz.length - 1, Math.floor(p * nz.length))];
  return [q(0.25), q(0.5), q(0.75)];
}

function Heatmap({ u }: { u: Usage }) {
  const { weeks, months, cuts } = useMemo(() => {
    const end = parse(u.to);
    let start = parse(u.from);
    start = new Date(start.getTime() - ((start.getDay() + 6) % 7) * DAY_MS);
    const weeks: string[][] = [];
    for (let d = start; d <= end; d = new Date(d.getTime() + DAY_MS)) {
      if (!weeks.length || weeks[weeks.length - 1].length === 7) weeks.push([]);
      weeks[weeks.length - 1].push(iso(d));
    }
    const months: { x: number; text: string }[] = [];
    weeks.forEach((w, i) => {
      const first = parse(w[0]);
      if (i === 0 || first.getDate() <= 7) {
        const text = first.toLocaleDateString(undefined, { month: "short" });
        const prev = months[months.length - 1];
        if (!prev || (prev.text !== text && i - prev.x >= 3)) months.push({ x: i, text });
      }
    });
    return { weeks, months, cuts: levels(Object.values(u.days).map((d) => d.tokens)) };
  }, [u]);
  const level = (t: number) => (t <= 0 ? 0 : t <= cuts[0] ? 1 : t <= cuts[1] ? 2 : t <= cuts[2] ? 3 : 4);
  const left = 28;
  const top = 14;
  const width = left + weeks.length * (CELL + GAP);
  const height = top + 7 * (CELL + GAP);
  return (
    <div>
      <svg className="heatmap" viewBox={`0 0 ${width} ${height}`} width="100%" style={{ maxWidth: width * 1.7, display: "block" }}
        role="img" aria-label={`Daily Claude token use from ${u.from} to ${u.to}`}>
        {months.map((m) => (
          <text key={`${m.x}-${m.text}`} x={left + m.x * (CELL + GAP)} y={9} fontSize={9} fill="var(--text-3)">{m.text}</text>
        ))}
        {["Mon", "Wed", "Fri"].map((d, i) => (
          <text key={d} x={0} y={top + (i * 2) * (CELL + GAP) + 9} fontSize={9} fill="var(--text-3)">{d}</text>
        ))}
        {weeks.map((w, wi) => w.map((day, di) => {
          const d = u.days[day];
          const future = day > u.to;
          return future ? null : (
            <rect key={day} x={left + wi * (CELL + GAP)} y={top + di * (CELL + GAP)} width={CELL} height={CELL} rx={2}
              fill={`var(--heat-${level(d?.tokens ?? 0)})`}>
              <title>{`${label(day)}: ${d ? `${fmtTokens(d.tokens)} tokens · ${d.sessions} session${d.sessions === 1 ? "" : "s"} · ${d.messages} replies` : "no Claude use"}`}</title>
            </rect>
          );
        }))}
      </svg>
      <div className="muted" style={{ fontSize: 11, display: "flex", gap: 4, alignItems: "center", justifyContent: "flex-end", marginTop: 4 }}>
        Less {[0, 1, 2, 3, 4].map((l) => <span key={l} style={{ width: 10, height: 10, borderRadius: 2, background: `var(--heat-${l})`, display: "inline-block" }} />)} More
      </div>
    </div>
  );
}

function Bars({ rows }: { rows: { key: string; name: React.ReactNode; value: number; title: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div>
      {rows.map((r) => (
        <div key={r.key} className="hbar" title={r.title}>
          <span className="name">{r.name}</span>
          <span className="track"><span className="fill" style={{ display: "block", width: `${(r.value / max) * 100}%` }} /></span>
          <span className="val">{fmtTokens(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function UsageCard() {
  const usage = useApi<Usage>("/api/usage", { poll: 300000 });
  const u = usage.data;
  if (!u || !Object.keys(u.days).length) return null;
  const T = u.totals;
  const share = (n: number) => (T.tokens ? `${Math.round((n / T.tokens) * 100)}%` : "");
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-head">Claude usage <span className="muted" style={{ fontWeight: 400 }}>last {u.recent_days} days</span></div>
      <div className="card-body usage-grid">
        <div>
          <div className="usage-tiles">
            <div className="usage-tile"><b>{fmtTokens(T.tokens)}</b><span>tokens</span></div>
            <div className="usage-tile"><b>{fmtTokens(T.output)}</b><span>output tokens</span></div>
            <div className="usage-tile"><b>{T.sessions}</b><span>sessions</span></div>
            <div className="usage-tile"><b>{T.messages.toLocaleString()}</b><span>replies</span></div>
          </div>
          <p className="usage-label">Tokens per day, last 26 weeks</p>
          <Heatmap u={u} />
        </div>
        <div>
          {u.models.length > 0 && <>
            <p className="usage-label">By model</p>
            <Bars rows={u.models.slice(0, 5).map((m) => ({
              key: m.model, name: modelName(m.model), value: m.tokens,
              title: `${m.model}: ${fmtTokens(m.tokens)} tokens (${share(m.tokens)}), ${m.messages.toLocaleString()} replies`,
            }))} />
          </>}
          {u.projects.length > 0 && <>
            <p className="usage-label" style={{ marginTop: 12 }}>By project</p>
            <Bars rows={u.projects.slice(0, 6).map((p) => ({
              key: `${p.project}-${p.project_id}`,
              name: p.project_id ? <a {...linkProps(href(p.project_id, "overview"))}>{p.project}</a> : <span className="muted">{p.project === "other" ? "other folders" : p.project}</span>,
              value: p.tokens, title: `${p.project}: ${fmtTokens(p.tokens)} tokens (${share(p.tokens)})`,
            }))} />
          </>}
          <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            From Claude Code's local transcripts. Tokens are input, output and cache writes; cache reads ({fmtTokens(T.cache_read)}) are left out.
          </p>
        </div>
      </div>
    </div>
  );
}
