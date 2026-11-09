import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` (UI on :5173) with `dsd ui --no-open` running the API on :8765.
// Build: outputs into the Python package so `dsd ui` serves it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/dsd/web/dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } },
  },
});
