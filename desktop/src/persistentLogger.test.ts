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
    expect(diagnosticsWereEnabled(dir)).toBe(true);
    persistDiagnosticsChoice(dir, false);
    expect(diagnosticsWereEnabled(dir)).toBe(false);
  });
});
