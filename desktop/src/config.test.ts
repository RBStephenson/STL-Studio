import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { HEALTH_POLL_TIMEOUT_MS, isBackendRetryUrl, resolveBackendExe } from "./config";

const exeName = process.platform === "win32" ? "stl-studio.exe" : "stl-studio";

/** Temporarily overrides process.platform for a resolveBackendExe() call —
 *  the dev path shape branches on it (STUDIO-351: Windows one-dir vs
 *  everywhere-else one-file), so both branches need direct coverage
 *  regardless of which OS actually runs the test. */
function withPlatform(platform: NodeJS.Platform, fn: () => void): void {
  const original = process.platform;
  Object.defineProperty(process, "platform", { value: platform });
  try {
    fn();
  } finally {
    Object.defineProperty(process, "platform", { value: original });
  }
}

describe("health poll ceiling", () => {
  it("gives a post-update antivirus scan room without a false 'failed to start' (STUDIO-341)", () => {
    // Guards against an accidental regression back toward the 30s ceiling
    // that produced a coin-flip false failure on a Norton machine.
    expect(HEALTH_POLL_TIMEOUT_MS).toBe(90_000);
  });
});

describe("backend retry URL", () => {
  it("accepts only the internal retry navigation", () => {
    expect(isBackendRetryUrl("stl-studio://retry-backend")).toBe(true);
    expect(isBackendRetryUrl("https://example.com/retry-backend")).toBe(false);
  });
});

describe("resolveBackendExe", () => {
  afterEach(() => {
    delete process.env.STL_BACKEND_EXE;
  });

  it("honours the STL_BACKEND_EXE override above all else", () => {
    process.env.STL_BACKEND_EXE = "/custom/backend.exe";
    const path = resolveBackendExe({
      packaged: true,
      resourcesPath: "/app/resources",
      repoRoot: "/repo",
    });
    expect(path).toBe("/custom/backend.exe");
  });

  it("ignores a blank/whitespace override", () => {
    process.env.STL_BACKEND_EXE = "   ";
    const path = resolveBackendExe({
      packaged: false,
      resourcesPath: "/app/resources",
      repoRoot: "/repo",
    });
    expect(path).not.toBe("   ");
    expect(path).toContain("dist-standalone");
  });

  it("resolves from resourcesPath when packaged", () => {
    const path = resolveBackendExe({
      packaged: true,
      resourcesPath: "/app/resources",
      repoRoot: "/repo",
    });
    expect(path).toContain("resources");
    expect(path).not.toContain("dist-standalone");
    expect(path.endsWith(exeName)).toBe(true);
  });

  it("resolves the dev dist-standalone path when not packaged", () => {
    const path = resolveBackendExe({
      packaged: false,
      resourcesPath: "/app/resources",
      repoRoot: "/repo",
    });
    expect(path).toContain("dist-standalone");
    expect(path.endsWith(exeName)).toBe(true);
  });

  it("nests the dev exe under stl-studio/ on Windows (one-dir, STUDIO-351)", () => {
    withPlatform("win32", () => {
      const path = resolveBackendExe({
        packaged: false,
        resourcesPath: "/app/resources",
        repoRoot: "/repo",
      });
      expect(path).toBe(join("/repo", "dist-standalone", "stl-studio", "stl-studio.exe"));
    });
  });

  it("keeps the dev exe flat (one-file) on non-Windows platforms", () => {
    withPlatform("linux", () => {
      const path = resolveBackendExe({
        packaged: false,
        resourcesPath: "/app/resources",
        repoRoot: "/repo",
      });
      expect(path).toBe(join("/repo", "dist-standalone", "stl-studio"));
    });
  });

  it("resolves the packaged path from the resources root regardless of platform", () => {
    withPlatform("win32", () => {
      const path = resolveBackendExe({
        packaged: true,
        resourcesPath: "/app/resources",
        repoRoot: "/repo",
      });
      expect(path).toBe(join("/app/resources", "stl-studio.exe"));
    });
  });
});
