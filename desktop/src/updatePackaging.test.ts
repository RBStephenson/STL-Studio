import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("Electron update packaging", () => {
  it("uses one ASCII-safe installer name for packaging and updater metadata", () => {
    const config = readFileSync(join(__dirname, "..", "electron-builder.yml"), "utf8");
    expect(config).toContain("artifactName: STL-Studio-Setup-${version}.${ext}");
  });

  it("fails the Windows build when latest.yml references missing assets", () => {
    const workflow = readFileSync(
      join(__dirname, "..", "..", ".github", "workflows", "build.yml"),
      "utf8",
    );
    expect(workflow).toContain("Validate Electron update artifact names");
    expect(workflow).toContain("latest.yml references missing installer");
    expect(workflow).toContain("Updater blockmap missing");
  });
});
