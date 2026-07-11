/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
    // Vitest runs all test files in parallel forks with no worker cap; on small
    // CI runners the heavy ImportPreviewPage render is starved of CPU and its
    // findBy waits time out (#596) — a load artifact, not a real failure. Retry
    // re-runs a failed test (a genuinely broken one still fails all attempts).
    retry: 2,
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    // Docker bind mounts on Windows/macOS don't propagate inotify events, so
    // the watcher must poll (set via CHOKIDAR_USEPOLLING in docker-compose.dev.yml).
    watch: process.env.CHOKIDAR_USEPOLLING
      ? { usePolling: true, interval: 300 }
      : undefined,
    proxy: {
      "/api": {
        // Docker: backend:8000 — Native: localhost:8000
        target: process.env.VITE_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
