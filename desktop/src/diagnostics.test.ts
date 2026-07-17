import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  assertTrustedDiagnosticsSender,
  patchConsoleForDiagnostics,
  registerDiagnosticsIpcHandlers,
  type ConsoleLike,
} from "./diagnostics";

vi.mock("./persistentLogger", () => ({
  persistDiagnosticsChoice: vi.fn(),
}));

import { persistDiagnosticsChoice } from "./persistentLogger";

function fakeConsole(): ConsoleLike {
  return { log: vi.fn(), warn: vi.fn(), error: vi.fn() };
}

function fakeEvent(url: string): { sender: { getURL: () => string } } {
  return { sender: { getURL: () => url } };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("patchConsoleForDiagnostics", () => {
  it("calls through to the original method and writes each level to the log", () => {
    const target = fakeConsole();
    const originalLog = target.log;
    const writeLog = vi.fn();

    patchConsoleForDiagnostics(target, writeLog);
    target.log("hello", 1);
    target.warn("careful");
    target.error("boom");

    expect(originalLog).toHaveBeenCalledWith("hello", 1);
    expect(writeLog).toHaveBeenCalledWith("INFO", ["hello", 1]);
    expect(writeLog).toHaveBeenCalledWith("WARNING", ["careful"]);
    expect(writeLog).toHaveBeenCalledWith("ERROR", ["boom"]);
  });

  it("returns the original unwrapped methods, bypassing the patch", () => {
    const target = fakeConsole();
    const originalLog = target.log;
    const writeLog = vi.fn();
    const original = patchConsoleForDiagnostics(target, writeLog);

    expect(original.log).not.toBe(target.log);
    original.log("direct");

    expect(originalLog).toHaveBeenCalledWith("direct");
    expect(writeLog).not.toHaveBeenCalled();
  });
});

describe("assertTrustedDiagnosticsSender", () => {
  it("allows http://localhost and http://127.0.0.1", () => {
    expect(() => assertTrustedDiagnosticsSender(fakeEvent("http://localhost:5173/app") as never)).not.toThrow();
    expect(() => assertTrustedDiagnosticsSender(fakeEvent("http://127.0.0.1:5173/app") as never)).not.toThrow();
  });

  it("rejects other protocols and hosts", () => {
    expect(() => assertTrustedDiagnosticsSender(fakeEvent("https://localhost/app") as never)).toThrow(
      /untrusted/,
    );
    expect(() => assertTrustedDiagnosticsSender(fakeEvent("http://evil.example.com/app") as never)).toThrow(
      /untrusted/,
    );
    expect(() => assertTrustedDiagnosticsSender(fakeEvent("file:///etc/passwd") as never)).toThrow(/untrusted/);
  });
});

describe("registerDiagnosticsIpcHandlers", () => {
  function setup() {
    const handlers = new Map<string, (...args: never[]) => unknown>();
    const ipcMain = {
      handle: vi.fn((channel: string, handler: (...args: never[]) => unknown) => {
        handlers.set(channel, handler);
      }),
    };
    const openPath = vi.fn().mockResolvedValue("");
    const setLogger = vi.fn();
    const createLogger = vi.fn().mockReturnValue({ write: vi.fn() });
    registerDiagnosticsIpcHandlers({
      ipcMain,
      logDir: "/logs",
      userDataDir: "/userdata",
      openPath,
      createLogger,
      setLogger,
    });
    return { handlers, openPath, setLogger, createLogger };
  }

  it("open-logs opens the log directory for a trusted sender", async () => {
    const { handlers, openPath } = setup();
    const result = await handlers.get("diagnostics:open-logs")!(fakeEvent("http://localhost/app") as never);
    expect(openPath).toHaveBeenCalledWith("/logs");
    expect(result).toBe("");
  });

  it("open-logs rejects an untrusted sender without opening anything", async () => {
    const { handlers, openPath } = setup();
    await expect(
      handlers.get("diagnostics:open-logs")!(fakeEvent("https://evil.example.com") as never),
    ).rejects.toThrow(/untrusted/);
    expect(openPath).not.toHaveBeenCalled();
  });

  it("set-enabled(true) persists the choice and installs a new logger", () => {
    const { handlers, setLogger, createLogger } = setup();
    handlers.get("diagnostics:set-enabled")!(fakeEvent("http://localhost/app") as never, true as never);
    expect(persistDiagnosticsChoice).toHaveBeenCalledWith("/userdata", true);
    expect(createLogger).toHaveBeenCalledWith("/logs");
    expect(setLogger).toHaveBeenCalledWith(createLogger.mock.results[0]?.value);
  });

  it("set-enabled(false) persists the choice and clears the logger", () => {
    const { handlers, setLogger, createLogger } = setup();
    handlers.get("diagnostics:set-enabled")!(fakeEvent("http://localhost/app") as never, false as never);
    expect(persistDiagnosticsChoice).toHaveBeenCalledWith("/userdata", false);
    expect(createLogger).not.toHaveBeenCalled();
    expect(setLogger).toHaveBeenCalledWith(null);
  });

  it("set-enabled rejects an untrusted sender without persisting anything", () => {
    const { handlers, setLogger } = setup();
    expect(() =>
      handlers.get("diagnostics:set-enabled")!(fakeEvent("http://evil.example.com") as never, true as never),
    ).toThrow(/untrusted/);
    expect(persistDiagnosticsChoice).not.toHaveBeenCalled();
    expect(setLogger).not.toHaveBeenCalled();
  });
});
