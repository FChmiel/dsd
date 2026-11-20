import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(path, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...(rest.headers || {}) } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const post = <T = any>(path: string, json: unknown) => api<T>(path, { method: "POST", json });
export const patch = <T = any>(path: string, json: unknown) => api<T>(path, { method: "PATCH", json });
export const put = <T = any>(path: string, json: unknown) => api<T>(path, { method: "PUT", json });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });

export function qs(params: Record<string, string | number | boolean | string[] | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.filter(Boolean).forEach((x) => sp.append(k, x));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Fetch JSON, with optional polling. Keeps the previous data while refetching (no flicker). */
export function useApi<T = any>(path: string | null, opts: { poll?: number } = {}) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pathRef = useRef(path);
  pathRef.current = path;
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
    const mine = ++seq.current;
    const current = () => pathRef.current === path && seq.current === mine;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (current()) {
        setData(d);
        setError(null);
      }
    } catch (e: any) {
      if (current()) setError(e.message || String(e));
    } finally {
      if (seq.current === mine) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setData(undefined);
    load();
  }, [load]);

  useEffect(() => {
    if (!opts.poll || !path) return;
    const t = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, opts.poll);
    return () => clearInterval(t);
  }, [opts.poll, path, load]);

  return { data, error, loading, reload: load, setData };
}

// ---------------------------------------------------------------- types

export type TaskStatus = "todo" | "doing" | "done" | "blocked" | "dropped";

export interface Task {
  id: string | null;
  status: TaskStatus;
  title: string;
  tags: string[];
  attrs: Record<string, string>;
  plan: string;
  parent: string | null;
  notes: string[];
}

export interface Project {
  id: string;
  name: string;
  root: string;
  repo: string;
  scope: string | null;
  data_dir: string;
  docs_dir: string;
}

export function tildify(path: string): string {
  return path.replace(/^\/Users\/[^/]+/, "~");
}

export function projectPath(p: Project): string {
  return tildify(p.scope ? `${p.repo}/${p.scope}` : p.repo);
}

export interface Run {
  id: string;
  name: string;
  benchmark: string | null;
  task: string | null;
  status: string;
  created_at: string;
  ended_at: string | null;
  git_sha: string | null;
  git_dirty: boolean;
  params: Record<string, any>;
  metrics: Record<string, number>;
  metric_stats: Record<string, { last: number; min: number; max: number; n: number; last_step: number | null }>;
  info: Record<string, any>;
  tags: string[];
  artifacts: number;
  error: string | null;
}

export const shortId = (id: string) => id.slice(-8).toLowerCase();

export function fmtNum(v: any): string {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v) && Math.abs(v) < 1e6) return String(v);
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(2);
  return Number(v.toPrecision(4)).toString();
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = Date.now();
  const s = (now - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
  return d.toLocaleDateString();
}

export function duration(a: string | null, b: string | null): string {
  if (!a) return "";
  const end = b ? new Date(b).getTime() : Date.now();
  const s = Math.max(0, (end - new Date(a).getTime()) / 1000);
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}
