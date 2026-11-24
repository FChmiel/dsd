import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { qs, useApi, type Run } from "../api";
import { href, linkProps, navigate } from "../router";
import { RunsTable, varyingParams } from "./bits";

/** Resolve a link relative to the current doc's folder (docs-relative paths). */
export function resolveDocPath(base: string | null, target: string): string {
  const dir = base && base.includes("/") ? base.slice(0, base.lastIndexOf("/")) : "";
  const parts = (target.startsWith("/") ? target.slice(1) : dir ? `${dir}/${target}` : target).split("/");
  const out: string[] = [];
  for (const p of parts) {
    if (p === "..") out.pop();
    else if (p && p !== ".") out.push(p);
  }
  return out.join("/");
}

function preprocess(md: string): string {
  // Obsidian-style embeds and wikilinks (outside code fences)
  const lines = md.split("\n");
  let fence = false;
  return lines
    .map((ln, i) => {
      if (/^\s*(```|~~~)/.test(ln)) fence = !fence;
      if (fence) return ln;
      if (/^\s+→\s/.test(lines[i + 1] ?? "") && ln.trim()) ln = `${ln.replace(/\s+$/, "")}  `;
      const embed = ln.match(/^\s*!\[\[([^\]]+)\]\]\s*$/);
      // Wikilinks resolve from the docs root (like an Obsidian vault), not the current folder.
      if (embed) return "```dsd-embed\n" + (embed[1].trim().startsWith("run:") ? "" : "/") + embed[1].trim() + "\n```";
      return ln.replace(/(?<!!)\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, p, label) => `[${label ?? p}](/${p.replace(/ /g, "%20")})`);
    })
    .join("\n");
}

function parseBlock(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  text.split("\n").forEach((ln) => {
    const m = ln.match(/^\s*([\w_]+)\s*:\s*(.+?)\s*$/);
    if (m) out[m[1]] = m[2];
  });
  return out;
}

function RunsEmbed({ pid, spec }: { pid: string; spec: string }) {
  const q = parseBlock(spec);
  const where = q.where ? q.where.split(/\s*;\s*|\s*,\s*(?=[\w.]+\s*(?:>=|<=|!=|==|=|>|<|~))/).filter(Boolean) : [];
  const url = `/api/p/${pid}/runs${qs({ benchmark: q.benchmark, task: q.task, status: q.status, tag: q.tag, sort: q.sort, limit: q.limit ?? 10, where })}`;
  const { data, error } = useApi<Run[]>(url, { poll: 15000 });
  const metricKeys = q.metrics ? q.metrics.split(/[,\s]+/).filter(Boolean)
    : Array.from(new Set((data ?? []).flatMap((r) => Object.keys(r.metrics)))).slice(0, 4);
  return (
    <div className="embed">
      <div className="embed-head"><span>dsd-runs</span><span className="spacer" />
        {Object.entries(q).map(([k, v]) => <span key={k}>{k}: {v}</span>)}
      </div>
      {error && <div className="error-box">{error}</div>}
      {data && data.length === 0 && <div className="empty">No matching runs</div>}
      {data && data.length > 0 && (
        <RunsTable pid={pid} runs={data} metricKeys={metricKeys} paramKeys={q.params ? q.params.split(/[,\s]+/) : varyingParams(data, 3)} compact />
      )}
    </div>
  );
}

function WhiteboardEmbed({ pid, path }: { pid: string; path: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const slug = path.match(/^whiteboards\/([^/]+)\.excalidraw$/)?.[1];
  useEffect(() => {
    let alive = true;
    Promise.all([fetch(`/api/p/${pid}/docs/raw/${path}`).then((r) => {
      if (!r.ok) throw new Error(r.status === 404 ? "not found" : r.statusText);
      return r.json();
    }), import("./WhiteboardEditor")])
      .then(([board, mod]) => mod.boardSvg(board, window.matchMedia("(prefers-color-scheme: dark)").matches))
      .then((el) => { if (alive) setSvg(el.outerHTML); })
      .catch((e) => { if (alive) setError(String(e?.message ?? e)); });
    return () => { alive = false; };
  }, [pid, path]);
  return (
    <div className="embed">
      <div className="embed-head"><span>{path}</span><span className="spacer" />
        {slug && <a {...linkProps(href(pid, "whiteboards", slug))}>edit ↗</a>}
      </div>
      {error ? <div className="muted" style={{ padding: 10 }}>Couldn't show this whiteboard: {error}</div>
        : svg ? <div className="board-embed" dangerouslySetInnerHTML={{ __html: svg }} />
        : <div className="muted" style={{ padding: 10 }}>Drawing whiteboard…</div>}
    </div>
  );
}

let diagramCount = 0;

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    import("mermaid").then(async ({ default: mermaid }) => {
      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral" });
      const { svg } = await mermaid.render(`dsd-diagram-${++diagramCount}`, code);
      if (alive) { setSvg(svg); setError(null); }
    }).catch((e) => { if (alive) setError(String(e?.message ?? e)); });
    return () => { alive = false; };
  }, [code]);
  if (error) {
    return (
      <div className="diagram diagram-error">
        <div className="muted">Couldn't draw this diagram: {error.split("\n")[0]}</div>
        <pre>{code}</pre>
      </div>
    );
  }
  if (!svg) return <div className="diagram muted">Drawing diagram…</div>;
  return <div className="diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}

function FileEmbed({ pid, path }: { pid: string; path: string }) {
  const src = path.startsWith("run:")
    ? (() => { const [rid, ...rest] = path.slice(4).split("/"); return `/api/p/${pid}/runs/${rid}/artifacts/${rest.join("/")}`; })()
    : `/api/p/${pid}/docs/raw/${path}`;
  const isImg = /\.(png|jpe?g|svg|gif|webp)$/i.test(path);
  return (
    <div className="embed">
      <div className="embed-head"><span>{path}</span><span className="spacer" />
        <a href={src} target="_blank" rel="noreferrer">open ↗</a>
      </div>
      {isImg ? <img src={src} alt={path} style={{ display: "block", maxWidth: "100%" }} />
        : <iframe src={src} sandbox="allow-scripts allow-popups" title={path} />}
    </div>
  );
}

export function Markdown({ pid, source, docPath }: { pid: string; source: string; docPath: string | null }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (/^\s*javascript:/i.test(url) ? "" : url)}
        components={{
          pre({ children, node, ...rest }) {
            const child: any = Array.isArray(children) ? children[0] : children;
            const cls: string = child?.props?.className ?? "";
            const text = String(child?.props?.children ?? "").replace(/\n$/, "");
            if (cls.includes("language-dsd-runs")) return <RunsEmbed pid={pid} spec={text} />;
            if (cls.includes("language-mermaid")) return <MermaidBlock code={text} />;
            if (cls.includes("language-dsd-embed")) {
              const t = text.trim();
              if (!t.startsWith("run:") && t.endsWith(".excalidraw")) return <WhiteboardEmbed pid={pid} path={resolveDocPath(docPath, t)} />;
              return <FileEmbed pid={pid} path={t.startsWith("run:") ? t : resolveDocPath(docPath, t)} />;
            }
            return <pre {...rest}>{children}</pre>;
          },
          a({ href: to, children, node, ...rest }) {
            const url = to ?? "";
            if (url.startsWith("run:")) return <a {...linkProps(href(pid, "runs", url.slice(4)))}>{children}</a>;
            if (url.startsWith("task:")) return <a {...linkProps(`${href(pid, "plans")}?task=${url.slice(5)}`)}>{children}</a>;
            if (/^[a-z]+:/i.test(url) || url.startsWith("#")) return <a href={url} target="_blank" rel="noreferrer" {...rest}>{children}</a>;
            const target = resolveDocPath(docPath, decodeURIComponent(url.split("#")[0]));
            if (target.startsWith("plans/") && target.endsWith(".md")) {
              return <a {...linkProps(href(pid, "plans", target.slice(6, -3)))}>{children}</a>;
            }
            return <a href={href(pid, "docs", target)} onClick={(e) => { e.preventDefault(); navigate(href(pid, "docs", target)); }}>{children}</a>;
          },
          img({ src, alt, node, ...rest }) {
            const s = src ?? "";
            const resolved = /^[a-z]+:/i.test(s) || s.startsWith("/") ? s : `/api/p/${pid}/docs/raw/${resolveDocPath(docPath, s)}`;
            return <img src={resolved} alt={alt} {...rest} />;
          },
        }}
      >
        {preprocess(source)}
      </ReactMarkdown>
    </div>
  );
}
