import { lazy, Suspense, useState } from "react";
import { del, post, useApi } from "../api";
import { useApp } from "../context";
import { href, linkProps, navigate } from "../router";
import { Icon } from "../components/Icon";
import type { Board } from "../components/WhiteboardEditor";
import type { SessionTarget } from "../components/SessionLauncher";

const WhiteboardEditor = lazy(() => import("../components/WhiteboardEditor"));

(window as any).EXCALIDRAW_ASSET_PATH = "/excalidraw/";

interface BoardInfo { slug: string; name: string; updated: number; shapes: number; pending: number }

function ago(ts: number): string {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function AskClaude({ prompt }: { prompt: string }) {
  const { sendToAgent, focusWorktree } = useApp();
  const [where, setWhere] = useState<"here" | "main" | "new">("here");
  const target: SessionTarget = where === "new" ? { mode: "new" }
    : where === "here" && focusWorktree ? { mode: "existing", worktree: focusWorktree } : { mode: "main" };
  return (
    <span className="ask-claude">
      <button className="btn" onClick={() => sendToAgent(prompt, { session: target })}>Ask Claude to draw</button>
      <select className="input" value={where} onChange={(e) => setWhere(e.target.value as typeof where)}
        title="Which Claude session gets the request">
        {focusWorktree && <option value="here">in ⎇ {focusWorktree}</option>}
        <option value={focusWorktree ? "main" : "here"}>on main checkout</option>
        <option value="new">in a new worktree</option>
      </select>
    </span>
  );
}

export function Whiteboards({ slug }: { slug: string | null }) {
  return slug ? <BoardPage key={slug} slug={slug} /> : <BoardList />;
}

function BoardList() {
  const { project, toast } = useApp();
  const boards = useApi<BoardInfo[]>(`/api/p/${project.id}/whiteboards`, { poll: 5000 });
  const list = boards.data ?? [];

  const create = async () => {
    const name = window.prompt("Name the whiteboard", "Untitled");
    if (name === null) return;
    try {
      const { slug } = await post<{ slug: string }>(`/api/p/${project.id}/whiteboards`, { name });
      navigate(href(project.id, "whiteboards", slug));
    } catch (e: any) {
      toast(e.message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Whiteboards</h1>
        <span className="sub">sketches and diagrams for this project</span>
        <span className="spacer" />
        <AskClaude prompt="Draw a diagram on a dsd whiteboard (whiteboard_draw) of " />
        <button className="btn primary" onClick={create}>New whiteboard</button>
      </div>
      {boards.error && <div className="error-box">{boards.error}</div>}
      {boards.data && list.length === 0 && (
        <div className="card"><div className="empty">
          No whiteboards yet. Start one, or ask Claude to draw a diagram: it can lay out a Mermaid flowchart or place
          boxes, diamonds and arrows on a board, and you can edit the result.
        </div></div>
      )}
      <div className="board-grid">
        {list.map((b) => (
          <a key={b.slug} className="card board-card" {...linkProps(href(project.id, "whiteboards", b.slug))}>
            <div className="board-name">{b.name}</div>
            <div className="muted" style={{ fontSize: 12 }}>
              {b.shapes} shape{b.shapes === 1 ? "" : "s"} · {ago(b.updated)}
              {b.pending > 0 && <span className="pill" style={{ marginLeft: 6 }}>Claude drew {b.pending}</span>}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

function BoardPage({ slug }: { slug: string }) {
  const { project, toast } = useApp();
  const url = `/api/p/${project.id}/whiteboards/${slug}`;
  const board = useApi<Board>(url);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const name = board.data?.dsd?.name ?? slug;

  const rename = async () => {
    const next = window.prompt("Rename whiteboard", name);
    if (!next || next === name) return;
    try {
      const r = await post<{ slug: string }>(`${url}/rename`, { name: next });
      navigate(href(project.id, "whiteboards", r.slug), true);
    } catch (e: any) {
      toast(e.message);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete the whiteboard "${name}"?`)) return;
    try {
      await del(url);
      navigate(href(project.id, "whiteboards"));
    } catch (e: any) {
      toast(e.message);
    }
  };

  return (
    <div className="page full board-page">
      <div className="board-bar">
        <a className="muted" {...linkProps(href(project.id, "whiteboards"))}>Whiteboards</a>
        <span className="muted">/</span>
        <b className="board-title" title={name}>{name}</b>
        <span className="muted" style={{ fontSize: 12 }}>{savedAt ? "saved" : ""}</span>
        <span className="spacer" />
        <button className="btn sm ghost" title={`Copy ![[whiteboards/${slug}.excalidraw]] to embed this board in a doc`}
          onClick={() => navigator.clipboard.writeText(`![[whiteboards/${slug}.excalidraw]]`).then(() => toast("Copied: paste it into a doc"))}>Copy embed</button>
        <AskClaude prompt={`On the dsd whiteboard "${name}" (whiteboard_read, then whiteboard_draw board="${name}"), draw `} />
        <button className="btn sm ghost" onClick={rename}>Rename</button>
        <button className="btn sm ghost" onClick={remove} title="Delete whiteboard"><Icon name="trash" /></button>
      </div>
      <div className="board-canvas">
        {board.error && <div className="error-box" style={{ margin: 16 }}>{board.error}</div>}
        {board.data && (
          <Suspense fallback={<div className="muted" style={{ padding: 20 }}>Loading whiteboard…</div>}>
            <WhiteboardEditor pid={project.id} slug={slug} initial={board.data} onError={toast} onSaved={setSavedAt} />
          </Suspense>
        )}
      </div>
    </div>
  );
}
