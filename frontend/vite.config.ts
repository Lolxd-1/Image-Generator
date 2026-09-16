/// vite.config.ts — build + dev-server config. Builds into ../backend/frontend_dist
/// (served as the SPA by FastAPI, see SPEC.md §7) and proxies /api to the
/// local backend during development.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/frontend_dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
