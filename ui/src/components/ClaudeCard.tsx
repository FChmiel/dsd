import { useState } from "react";
import { post, tildify, useApi } from "../api";

interface ClaudeStatus {
  mcp: { state: "connected" | "missing" | "stale"; command: string[] | null; expected: string[]; claude_cli: boolean };
  skills: { name: string; state: "missing" | "current" | "outdated" | "edited" }[];
}

export function ClaudeCard({ compact }: { compact?: boolean }) {
  const status = useApi<ClaudeStatus>("/api/claude", { poll: 30000 });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const s = status.data;
  if (!s) return null;
  const pending = s.skills.filter((k) => k.state === "missing" || k.state === "outdated");
  const ok = s.mcp.state === "connected" && pending.length === 0;
  if (ok && !msg) return null;

  const connect = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await post("/api/claude/connect", {});
      setMsg("Claude Code is connected. New Claude sessions have dsd's tools and skills.");
      status.reload();
    } catch (e: any) {
      setMsg(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const problem = s.mcp.state === "stale"
    ? <>Claude Code runs a different dsd (<code>{tildify(s.mcp.command?.[0] ?? "?")}</code>), so its tools may be out of date.</>
    : s.mcp.state === "missing"
      ? <>Claude sessions you start from the dsd app already have dsd's tools. Connect once to give Claude Code in your own terminal or editor the same tools and skills.</>
      : <>{pending.length} dsd skill{pending.length > 1 ? "s" : ""} to install or update: <span className="mono muted">{pending.map((k) => k.name).join(", ")}</span>.</>;
  const label = s.mcp.state === "stale" ? "Fix connection" : "Connect Claude Code";

  if (compact) {
    return (
      <div className="card" style={{ margin: "8px 10px 0", padding: "8px 10px", fontSize: 12.5 }}>
        <div>{ok ? msg : problem}</div>
        {!ok && <button className="btn sm primary" style={{ marginTop: 6 }} disabled={busy} onClick={connect}>{busy ? "Connecting…" : label}</button>}
        {!ok && msg && <div className="muted" style={{ marginTop: 6 }}>{msg}</div>}
      </div>
    );
  }
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-head">Claude Code</div>
      <div className="card-body">
        <p className="dim" style={{ marginTop: 0 }}>{ok ? msg : problem}</p>
        {!ok && (
          <>
            <p className="muted" style={{ fontSize: 12.5 }}>
              This registers the dsd MCP server for your user ({tildify(s.mcp.expected.join(" "))}) and installs dsd's skills in
              <code> ~/.claude/skills</code>. Skills you have edited are kept.
            </p>
            <button className="btn primary" disabled={busy} onClick={connect}>{busy ? "Connecting…" : label}</button>
            {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
          </>
        )}
      </div>
    </div>
  );
}
