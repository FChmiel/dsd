import { useState } from "react";
import { post, useApi } from "../api";
import { inApp } from "../native";

/** Packaged app only: offer to link the bundled `dsd` CLI onto PATH if it isn't there. */
export function CliCard({ compact }: { compact?: boolean }) {
  const cli = useApi<any>(inApp ? "/api/cli" : null);
  const [msg, setMsg] = useState<string | null>(null);
  if (!inApp || !cli.data?.frozen || cli.data.on_path) return null;
  const install = async () => {
    try {
      const r = await post<any>("/api/cli/install", {});
      setMsg(r.on_path ? `Installed: ${r.linked}` : `Linked ${r.linked}. ${r.hint}`);
      cli.reload();
    } catch (e: any) { setMsg(e.message); }
  };
  if (compact) {
    return <button className="btn sm ghost" title="Link the bundled dsd command into ~/.local/bin so Claude Code outside the app can use it" onClick={install}>Install dsd command</button>;
  }
  return (
    <div className="card">
      <div className="card-head">Command-line tool</div>
      <div className="card-body">
        <p className="dim" style={{ marginTop: 0 }}>
          Sessions inside the app already have <code>dsd</code>. To use <code>dsd exec</code>, <code>dsd wt</code> and the MCP server from
          your own terminal or editor, link the bundled command into <code>~/.local/bin</code>.
        </p>
        <button className="btn" onClick={install}>Install dsd command</button>
        {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
      </div>
    </div>
  );
}
