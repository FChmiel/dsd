import { createContext, useContext } from "react";
import type { Project } from "./api";
import type { SessionTarget } from "./components/SessionLauncher";
import type { TermInfo } from "./components/TerminalPane";

export interface AppCtx {
  project: Project;
  /** Paste text into the active agent terminal (starting Claude if none is open). */
  sendToAgent: (text: string, opts?: { submit?: boolean; terminalId?: string; session?: SessionTarget }) => Promise<void>;
  terminals: TermInfo[];
  newSession: (kind: "claude" | "shell", target?: SessionTarget) => Promise<TermInfo>;
  openLauncher: () => void;
  activeTerminal: string | null;
  /** Worktree the workspace is focused on: the active session's, else the one dsd was opened from; null = main checkout. */
  focusWorktree: string | null;
  toast: (msg: string) => void;
}

export const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}
