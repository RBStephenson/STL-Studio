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
    // A test failure must remain visible. Global retries previously allowed
    // intermittent async/query races to pass on a later attempt.
    retry: 0,
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "html"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test-setup.ts"],
      thresholds: {
        statements: 62,
        branches: 58,
        functions: 54,
        lines: 65,
      },
    },
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
