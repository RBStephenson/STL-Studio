import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Sidecar logic only; no Electron/DOM needed, so the fast node env is fine.
    environment: "node",
    include: ["src/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "html"],
      reportsDirectory: "coverage",
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts"],
      thresholds: {
        statements: 48,
        branches: 83,
        functions: 86,
        lines: 48,
      },
    },
  },
});
