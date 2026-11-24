import { useCallback, useEffect, useRef, useState } from "react";
import {
  CaptureUpdateAction, Excalidraw, convertToExcalidrawElements, getCommonBounds, getSceneVersion, exportToSvg,
} from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI, BinaryFiles, AppState } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import "@excalidraw/excalidraw/index.css";
import { api, put } from "../api";

export interface Pending { id: string; mermaid?: string; elements?: any[]; replace?: boolean }
export interface Board {
  elements: ExcalidrawElement[];
  appState?: Partial<AppState>;
  files?: BinaryFiles;
  dsd: { name?: string; pending?: Pending[] };
}

const GAP = 120;
const KEEP_STATE = ["viewBackgroundColor", "gridSize", "gridModeEnabled"] as const;

function useDark() {
  const [dark, setDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const q = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setDark(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return dark;
}

const ARROW_GAP = 6;

function edgeFraction(shape: any, dx: number, dy: number): number {
  const rx = (shape.width ?? 100) / 2;
  const ry = (shape.height ?? 100) / 2;
  const ax = Math.abs(dx) / rx;
  const ay = Math.abs(dy) / ry;
  if (shape.type === "ellipse") return 1 / Math.hypot(ax, ay);
  if (shape.type === "diamond") return 1 / (ax + ay);
  return 1 / Math.max(ax, ay);
}

function routeArrows(skeletons: any[]): any[] {
  const byId = new Map(skeletons.filter((s) => s.id).map((s) => [s.id, s]));
  const placed = (s: any) => s && typeof s.x === "number" && typeof s.y === "number";
  return skeletons.map((s) => {
    if ((s.type !== "arrow" && s.type !== "line") || s.points) return s;
    const from = byId.get(s.start?.id);
    const to = byId.get(s.end?.id);
    if (!placed(from) || !placed(to)) return s;
    const ax = from.x + (from.width ?? 100) / 2, ay = from.y + (from.height ?? 100) / 2;
    const bx = to.x + (to.width ?? 100) / 2, by = to.y + (to.height ?? 100) / 2;
    const dx = bx - ax, dy = by - ay;
    const len = Math.hypot(dx, dy);
    if (!len) return s;
    const t0 = edgeFraction(from, dx, dy) + ARROW_GAP / len;
    const t1 = 1 - edgeFraction(to, -dx, -dy) - ARROW_GAP / len;
    if (t1 <= t0) return s;
    return { ...s, x: ax + dx * t0, y: ay + dy * t0, width: dx * (t1 - t0), height: dy * (t1 - t0) };
  });
}

async function fontsReady() {
  try {
    await Promise.all(["Excalifont", "Virgil", "Nunito"].map((f) => document.fonts.load(`20px ${f}`)));
  } catch {
    return;
  }
}

async function toElements(p: Pending): Promise<{ elements: ExcalidrawElement[]; files: BinaryFiles }> {
  await fontsReady();
  if (p.mermaid) {
    const { parseMermaidToExcalidraw } = await import("@excalidraw/mermaid-to-excalidraw");
    const { elements, files } = await parseMermaidToExcalidraw(p.mermaid);
    return { elements: convertToExcalidrawElements(elements as any) as ExcalidrawElement[], files: (files ?? {}) as BinaryFiles };
  }
  return { elements: convertToExcalidrawElements(routeArrows(p.elements ?? [])) as ExcalidrawElement[], files: {} };
}

function placeRightOf(existing: readonly ExcalidrawElement[], added: ExcalidrawElement[]): ExcalidrawElement[] {
  const live = existing.filter((e) => !e.isDeleted);
  if (!live.length || !added.length) return added;
  const [, minY, maxX] = getCommonBounds(live);
  const [aMinX, aMinY] = getCommonBounds(added);
  const dx = maxX + GAP - aMinX;
  const dy = minY - aMinY;
  return added.map((e) => ({ ...e, x: e.x + dx, y: e.y + dy }));
}

export default function WhiteboardEditor({ pid, slug, initial, onError, onSaved }: {
  pid: string;
  slug: string;
  initial: Board;
  onError: (msg: string) => void;
  onSaved: (at: number) => void;
}) {
  const dark = useDark();
  const [excal, setExcal] = useState<ExcalidrawImperativeAPI | null>(null);
  const savedVersion = useRef(getSceneVersion(initial.elements));
  const timer = useRef<number | undefined>(undefined);
  const applying = useRef(false);
  const appliedIds = useRef(new Set<string>());
  const url = `/api/p/${pid}/whiteboards/${slug}`;

  const save = useCallback(async (applied: string[] = []) => {
    if (!excal) return;
    const elements = excal.getSceneElementsIncludingDeleted();
    const st = excal.getAppState();
    const appState = Object.fromEntries(KEEP_STATE.map((k) => [k, st[k]]));
    const files = excal.getFiles();
    const used = new Set(elements.filter((e) => !e.isDeleted && "fileId" in e).map((e: any) => e.fileId));
    try {
      await put(url, { scene: { elements: elements.filter((e) => !e.isDeleted), appState, files: Object.fromEntries(Object.entries(files).filter(([id]) => used.has(id))) }, applied });
      savedVersion.current = getSceneVersion(elements);
      onSaved(Date.now());
    } catch (e: any) {
      onError(`Couldn't save: ${e.message}`);
    }
  }, [excal, url, onError, onSaved]);

  const applyPending = useCallback(async (queued: Pending[]) => {
    const pending = queued.filter((p) => !appliedIds.current.has(p.id));
    if (!excal || !pending.length || applying.current) return;
    pending.forEach((p) => appliedIds.current.add(p.id));
    applying.current = true;
    try {
      let scene: ExcalidrawElement[] = [...excal.getSceneElementsIncludingDeleted()];
      const done: string[] = [];
      const added: ExcalidrawElement[] = [];
      for (const p of pending) {
        try {
          const { elements, files } = await toElements(p);
          if (p.replace) scene = scene.map((e) => ({ ...e, isDeleted: true }));
          const placed = placeRightOf(scene, elements);
          scene = [...scene, ...placed];
          added.push(...placed);
          if (Object.keys(files).length) excal.addFiles(Object.values(files));
        } catch (e: any) {
          onError(`Couldn't draw Claude's diagram: ${e.message ?? e}`);
        }
        done.push(p.id);
      }
      excal.updateScene({ elements: scene, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
      if (added.length) excal.scrollToContent(added, { fitToContent: true, animate: true });
      await save(done);
    } finally {
      applying.current = false;
    }
  }, [excal, save, onError]);

  useEffect(() => {
    if (!excal) return;
    applyPending(initial.dsd?.pending ?? []);
    const t = window.setInterval(async () => {
      try {
        const b = await api<Board>(url);
        if (b.dsd?.pending?.length) applyPending(b.dsd.pending);
      } catch {
        return;
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [excal]);

  useEffect(() => () => {
    if (timer.current) {
      window.clearTimeout(timer.current);
      save();
    }
  }, [save]);

  const onChange = (elements: readonly ExcalidrawElement[]) => {
    if (applying.current || getSceneVersion(elements) === savedVersion.current) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { timer.current = undefined; save(); }, 700);
  };

  return (
    <Excalidraw
      excalidrawAPI={setExcal}
      initialData={{
        elements: initial.elements,
        appState: { ...initial.appState, currentItemRoundness: "round" },
        files: initial.files,
        scrollToContent: true,
      }}
      onChange={onChange}
      theme={dark ? "dark" : "light"}
      name={initial.dsd?.name}
      UIOptions={{ canvasActions: { loadScene: false, saveToActiveFile: false, export: { saveFileToDisk: true } } }}
    />
  );
}

export async function boardSvg(board: Board, dark: boolean): Promise<SVGSVGElement> {
  return exportToSvg({
    elements: board.elements.filter((e) => !e.isDeleted),
    appState: { ...board.appState, exportBackground: false, exportWithDarkMode: dark },
    files: board.files ?? {},
  });
}
