import { useEffect, useMemo, useRef, useState } from "react";
import { fmtNum } from "../api";

export interface Series {
  name: string;
  color: string;
  points: [number, number][];
}

/** Categorical slots in fixed order (never cycled). Callers fold series beyond 8. */
export const SLOTS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const err = step0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

export function LineChart({ series, height = 200, title, subtitle }: {
  series: Series[]; height?: number; title?: string; subtitle?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(480);
  const [hover, setHover] = useState<{ x: number; px: number; py: number } | null>(null);

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(200, e.contentRect.width)));
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const m = { top: 8, right: 12, bottom: 22, left: 52 };
  const W = width - m.left - m.right;
  const H = height - m.top - m.bottom;

  const { xTicks, yTicks, sx, sy, xs } = useMemo(() => {
    const all = series.flatMap((s) => s.points);
    const xsAll = all.map((p) => p[0]);
    const ysAll = all.map((p) => p[1]);
    const xMin = Math.min(...xsAll), xMax = Math.max(...xsAll);
    const yt = niceTicks(Math.min(...ysAll), Math.max(...ysAll), 4);
    const xt = niceTicks(xMin, xMax, Math.max(2, Math.floor(W / 90))).filter((t) => t >= xMin && t <= xMax);
    const y0 = yt[0] ?? 0, y1 = yt[yt.length - 1] ?? 1;
    const sx = (x: number) => (xMax === xMin ? W / 2 : ((x - xMin) / (xMax - xMin)) * W);
    const sy = (y: number) => H - ((y - y0) / (y1 - y0 || 1)) * H;
    const xs = Array.from(new Set(xsAll)).sort((a, b) => a - b);
    return { xTicks: xt, yTicks: yt, sx, sy, xs };
  }, [series, W, H]);

  if (!series.length || !series.some((s) => s.points.length)) return <div className="muted">No data</div>;

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = (e.target as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    // nearest x value
    let best = xs[0], bd = Infinity;
    for (const x of xs) {
      const d = Math.abs(sx(x) - px);
      if (d < bd) { bd = d; best = x; }
    }
    setHover({ x: best, px: sx(best), py: e.clientY - rect.top });
  };

  const hoverVals = hover
    ? series.map((s) => {
        let best: [number, number] | null = null, bd = Infinity;
        for (const p of s.points) {
          const d = Math.abs(p[0] - hover.x);
          if (d < bd) { bd = d; best = p; }
        }
        return { s, p: best && bd === 0 ? best : null };
      }).filter((v) => v.p)
    : [];

  return (
    <div className="chart" ref={wrap}>
      {title && <div className="chart-title">{title}{subtitle && <span className="muted">{subtitle}</span>}</div>}
      {series.length >= 2 && (
        <div className="legend">
          {series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}
        </div>
      )}
      <svg width={width} height={height} role="img" aria-label={title}>
        <g transform={`translate(${m.left},${m.top})`}>
          <g className="axis">
            {yTicks.map((t) => (
              <g key={t}>
                <line className="gridline" x1={0} x2={W} y1={sy(t)} y2={sy(t)} />
                <text x={-8} y={sy(t)} dy="0.32em" textAnchor="end">{fmtNum(t)}</text>
              </g>
            ))}
            {xTicks.map((t) => (
              <text key={t} x={sx(t)} y={H + 15} textAnchor="middle">{fmtNum(t)}</text>
            ))}
          </g>
          {series.map((s) => {
            const pts = [...s.points].sort((a, b) => a[0] - b[0]);
            const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
            return (
              <g key={s.name}>
                <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {pts.length === 1 && <circle cx={sx(pts[0][0])} cy={sy(pts[0][1])} r={4} fill={s.color} />}
              </g>
            );
          })}
          {hover && (
            <g pointerEvents="none">
              <line x1={hover.px} x2={hover.px} y1={0} y2={H} stroke="var(--text-3)" strokeDasharray="3 3" />
              {hoverVals.map(({ s, p }) => (
                <circle key={s.name} cx={sx(p![0])} cy={sy(p![1])} r={4.5} fill={s.color} stroke="var(--panel)" strokeWidth={2} />
              ))}
            </g>
          )}
          <rect width={W} height={H} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </g>
      </svg>
      {hover && hoverVals.length > 0 && (
        <div className="tip" style={{
          left: Math.min(m.left + hover.px + 14, width - 190), top: Math.max(0, hover.py - 10) + (series.length >= 2 ? 24 : 0),
        }}>
          <div className="muted" style={{ fontSize: 11, marginBottom: 3 }}>step {fmtNum(hover.x)}</div>
          {hoverVals.map(({ s, p }) => (
            <div className="row" key={s.name}>
              <span className="sw" style={{ background: s.color }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", maxWidth: 160 }}>{s.name}</span>
              <span className="v">{fmtNum(p![1])}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
