import { createContext, useContext } from "react";
import type { Project } from "./api";

export interface AppCtx {
  project: Project;
  /** Paste text into the active agent terminal (starting Claude if none is open). */
  sendToAgent: (text: string, opts?: { submit?: boolean; terminalId?: string }) => Promise<void>;
  terminals: { id: string; title: string; kind: string }[];
  activeTerminal: string | null;
  toast: (msg: string) => void;
}

export const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}
