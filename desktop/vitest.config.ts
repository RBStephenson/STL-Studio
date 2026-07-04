import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Sidecar logic only; no Electron/DOM needed, so the fast node env is fine.
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
