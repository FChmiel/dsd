import { useState } from "react";
import { useApi } from "../api";
import { useApp } from "../context";
import { href, linkProps } from "../router";
import { Markdown } from "../components/Markdown";

interface Post {
  path: string;
  title: string;
  date: string;
  headline: string;
  metrics: Record<string, string | number>;
  task: string | null;
  plan: string | null;
  benchmark: string | null;
  runs: string[];
}

function innerLink(to: string) {
  const lp = linkProps(to);
  return { href: lp.href, onClick: (e: React.MouseEvent) => { e.stopPropagation(); lp.onClick(e); } };
}

export function Analytics() {
  const { project, sendToAgent } = useApp();
  const posts = useApi<Post[]>(`/api/p/${project.id}/analytics`, { poll: 10000 });
  const [open, setOpen] = useState<string | null>(null);
  const list = posts.data ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <h1>Analytics</h1>
        <span className="sub">key results from this project, newest first</span>
        <span className="spacer" />
        <button className="btn primary" onClick={() => sendToAgent("/dsd-results ")}>Ask Claude to post results</button>
      </div>
      {posts.error && <div className="error-box">{posts.error}</div>}
      {posts.data && list.length === 0 && (
        <div className="card"><div className="empty">
          No results posted yet. Ask Claude to post one (<code>/dsd-results</code>) after a benchmark run, an experiment or a finished task.
        </div></div>
      )}
      <div className="stack" style={{ gap: 12 }}>
        {list.map((p) => (
          <div key={p.path} className="card result-card">
            <div className="card-body" style={{ cursor: "pointer" }} onClick={() => setOpen(open === p.path ? null : p.path)}>
              <div className="result-head">
                <b className="result-title">{p.title}</b>
                <span className="muted mono" style={{ fontSize: 12 }}>{p.date}</span>
                <span className="spacer" />
                {p.task && <a className="pill" {...innerLink(`${href(project.id, "plans")}?task=${p.task}`)}>{p.task}</a>}
                {p.benchmark && <a className="pill" {...innerLink(href(project.id, "benchmarks", p.benchmark))}>{p.benchmark}</a>}
              </div>
              {p.headline && <div className="result-headline">{p.headline}</div>}
              {Object.keys(p.metrics).length > 0 && (
                <div className="result-metrics">
                  {Object.entries(p.metrics).map(([k, v]) => (
                    <div key={k} className="result-metric"><b>{String(v)}</b><span>{k}</span></div>
                  ))}
                </div>
              )}
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{open === p.path ? "Hide details ▴" : "Show details ▾"}</div>
            </div>
            {open === p.path && <PostBody pid={project.id} path={p.path} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function PostBody({ pid, path }: { pid: string; path: string }) {
  const doc = useApi<{ content: string }>(`/api/p/${pid}/docs/file?path=${encodeURIComponent(path)}`);
  if (doc.error) return <div className="card-body"><div className="error-box">{doc.error}</div></div>;
  if (!doc.data) return <div className="card-body muted">Loading…</div>;
  const body = doc.data.content.replace(/^---\n[\s\S]*?\n---\n/, "").replace(/^\s*#\s+.+\n+/, "").replace(/^\s*\*\*.+\*\*\s*\n+/, "");
  return (
    <div className="card-body" style={{ borderTop: "1px solid var(--border)" }}>
      <Markdown pid={pid} source={body} docPath={path} />
      <a className="muted" style={{ fontSize: 12 }} {...linkProps(href(pid, "docs", path))}>Open as a doc →</a>
    </div>
  );
}
