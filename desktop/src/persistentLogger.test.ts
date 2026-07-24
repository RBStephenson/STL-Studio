import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DESKTOP_LOG_MAX_BYTES,
  PersistentLogger,
  diagnosticsWereEnabled,
  persistDiagnosticsChoice,
  sanitizeDesktopLog,
} from "./persistentLogger";

describe("persistent desktop diagnostics", () => {
  it("redacts credentials and private paths", () => {
    const text = sanitizeDesktopLog(
      'Bearer abc123 "api_key": "hidden" C:\\Users\\Brent\\private.stl /mnt/nas/private.stl',
    );
    expect(text).not.toContain("abc123");
    expect(text).not.toContain("hidden");
    expect(text).not.toContain("Brent");
    expect(text).toContain("<redacted>");
  });

  it("rotates a bounded logfile", () => {
    const dir = mkdtempSync(join(tmpdir(), "stl-logs-"));
    writeFileSync(join(dir, "desktop.log"), "x".repeat(DESKTOP_LOG_MAX_BYTES), "utf8");
    new PersistentLogger(dir).write("INFO", ["next"]);
    expect(readFileSync(join(dir, "desktop.log.1"), "utf8")).toContain("xxx");
    expect(readFileSync(join(dir, "desktop.log"), "utf8")).toContain("next");
  });

  it("persists the enabled choice across restarts", () => {
    const dir = mkdtempSync(join(tmpdir(), "stl-marker-"));
    persistDiagnosticsChoice(dir, true);
    expect(diagnosticsWereEnabled(dir, {})).toBe(true);
    persistDiagnosticsChoice(dir, false);
    expect(diagnosticsWereEnabled(dir, {})).toBe(false);
  });

  describe("diagnosticsWereEnabled env-var bypass (STUDIO-352)", () => {
    it("is true from the env var alone, with no marker file", () => {
      const dir = mkdtempSync(join(tmpdir(), "stl-marker-"));
      expect(diagnosticsWereEnabled(dir, { STL_STUDIO_DIAGNOSTICS: "1" })).toBe(true);
    });

    it("treats an explicit \"0\" as not set", () => {
      const dir = mkdtempSync(join(tmpdir(), "stl-marker-"));
      expect(diagnosticsWereEnabled(dir, { STL_STUDIO_DIAGNOSTICS: "0" })).toBe(false);
    });

    it("is true from the marker file alone, with no env var", () => {
      const dir = mkdtempSync(join(tmpdir(), "stl-marker-"));
      persistDiagnosticsChoice(dir, true);
      expect(diagnosticsWereEnabled(dir, {})).toBe(true);
    });

    it("is false when neither is set", () => {
      const dir = mkdtempSync(join(tmpdir(), "stl-marker-"));
      expect(diagnosticsWereEnabled(dir, {})).toBe(false);
    });

    it("defaults to reading process.env when no env is passed", () => {
      const dir = mkdtempSync(join(tmpdir(), "stl-marker-"));
      const original = process.env.STL_STUDIO_DIAGNOSTICS;
      process.env.STL_STUDIO_DIAGNOSTICS = "1";
      try {
        expect(diagnosticsWereEnabled(dir)).toBe(true);
      } finally {
        if (original === undefined) delete process.env.STL_STUDIO_DIAGNOSTICS;
        else process.env.STL_STUDIO_DIAGNOSTICS = original;
      }
    });
  });
});
