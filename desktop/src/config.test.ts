import { afterEach, describe, expect, it } from "vitest";

import { resolveBackendExe } from "./config";

const exeName = process.platform === "win32" ? "stl-library.exe" : "stl-library";

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
});
