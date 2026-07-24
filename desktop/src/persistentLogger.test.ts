import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DESKTOP_LOG_BACKUPS,
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

  it("rotates a bounded logfile using the in-memory size seeded at construction (STUDIO-342)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "stl-logs-"));
    writeFileSync(join(dir, "desktop.log"), "x".repeat(DESKTOP_LOG_MAX_BYTES), "utf8");
    const logger = new PersistentLogger(dir);
    logger.write("INFO", ["next"]);
    await logger.flush();
    expect(readFileSync(join(dir, "desktop.log.1"), "utf8")).toContain("xxx");
    expect(readFileSync(join(dir, "desktop.log"), "utf8")).toContain("next");
  });

  it("preserves DESKTOP_LOG_BACKUPS generations across repeated rotations", async () => {
    const dir = mkdtempSync(join(tmpdir(), "stl-logs-"));
    const logger = new PersistentLogger(dir);
    // Each line alone exceeds the threshold, so every write rotates in turn —
    // driven entirely by the logger's own tracked size, not external file
    // tampering (which the in-memory counter can no longer see between writes).
    const oversized = "x".repeat(DESKTOP_LOG_MAX_BYTES);
    for (let i = 0; i < DESKTOP_LOG_BACKUPS + 2; i += 1) {
      logger.write("INFO", [`chunk-${i}`, oversized]);
      await logger.flush();
    }
    for (let generation = 1; generation <= DESKTOP_LOG_BACKUPS; generation += 1) {
      expect(existsSync(join(dir, `desktop.log.${generation}`))).toBe(true);
    }
    expect(existsSync(join(dir, `desktop.log.${DESKTOP_LOG_BACKUPS + 1}`))).toBe(false);
  });

  it("buffers writes and lands them all on disk after an explicit flush", async () => {
    const dir = mkdtempSync(join(tmpdir(), "stl-logs-"));
    const logger = new PersistentLogger(dir);
    logger.write("INFO", ["first"]);
    logger.write("INFO", ["second"]);
    logger.write("INFO", ["third"]);
    // Nothing on disk yet — the scheduled flush hasn't fired.
    expect(existsSync(join(dir, "desktop.log"))).toBe(false);

    await logger.flush();

    const content = readFileSync(join(dir, "desktop.log"), "utf8");
    expect(content).toContain("first");
    expect(content).toContain("second");
    expect(content).toContain("third");
  });

  it("swallows a flush failure instead of throwing (diagnostics must never break the app)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "stl-logs-"));
    const logger = new PersistentLogger(dir);
    // Replace the log path with a directory so the append can never succeed —
    // a stand-in for any real-world write failure (permissions, disk full).
    mkdirSync(join(dir, "desktop.log"));
    logger.write("INFO", ["boom"]);
    await expect(logger.flush()).resolves.toBeUndefined();
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
