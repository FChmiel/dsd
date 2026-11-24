import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const OUT = "../src/dsd/web/dist";

function excalidrawFonts(): Plugin {
  const src = resolve(__dirname, "node_modules/@excalidraw/excalidraw/dist/prod/fonts");
  return {
    name: "dsd-excalidraw-fonts",
    apply: "build",
    closeBundle() {
      if (!existsSync(src)) return;
      cpSync(src, resolve(__dirname, OUT, "excalidraw/fonts"), {
        recursive: true,
        filter: (path) => !path.includes("/Xiaolai"),
      });
    },
  };
}

// Dev: `npm run dev` (UI on :5173) with `dsd ui --no-open` running the API on :8765.
// Build: outputs into the Python package so `dsd ui` serves it.
export default defineConfig({
  plugins: [react(), excalidrawFonts()],
  build: { outDir: OUT, emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } },
  },
});
