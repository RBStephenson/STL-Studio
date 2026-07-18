import type { IpcMain, IpcMainInvokeEvent } from "electron";

import type { PersistentLogger } from "./persistentLogger";
import { persistDiagnosticsChoice } from "./persistentLogger";

export type ConsoleLike = {
  log(...values: unknown[]): void;
  warn(...values: unknown[]): void;
  error(...values: unknown[]): void;
};

export type LogWriter = (level: string, values: unknown[]) => void;

/** Wraps console.log/warn/error on `target` so every call also goes to the
 *  persistent log (via `writeLog`), then still calls through to the original
 *  method. Returns the original (unwrapped) methods. */
export function patchConsoleForDiagnostics(target: ConsoleLike, writeLog: LogWriter): ConsoleLike {
  const original: ConsoleLike = {
    log: target.log.bind(target),
    warn: target.warn.bind(target),
    error: target.error.bind(target),
  };
  target.log = (...values: unknown[]) => {
    original.log(...values);
    writeLog("INFO", values);
  };
  target.warn = (...values: unknown[]) => {
    original.warn(...values);
    writeLog("WARNING", values);
  };
  target.error = (...values: unknown[]) => {
    original.error(...values);
    writeLog("ERROR", values);
  };
  return original;
}

/** Rejects diagnostics IPC requests from anything other than the app's own
 *  localhost-served renderer, so a page navigated to in error can't read logs
 *  off disk or toggle diagnostics. */
export function assertTrustedDiagnosticsSender(event: IpcMainInvokeEvent): void {
  const source = new URL(event.sender.getURL());
  if (source.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(source.hostname)) {
    throw new Error("Diagnostics request rejected from an untrusted page");
  }
}

export type DiagnosticsIpcDeps = {
  ipcMain: Pick<IpcMain, "handle">;
  logDir: string;
  userDataDir: string;
  openPath: (path: string) => Promise<string>;
  createLogger: (directory: string) => PersistentLogger;
  setLogger: (logger: PersistentLogger | null) => void;
};

/** Registers the diagnostics:open-logs and diagnostics:set-enabled IPC
 *  handlers. Both reject requests from untrusted senders first. */
export function registerDiagnosticsIpcHandlers(deps: DiagnosticsIpcDeps): void {
  deps.ipcMain.handle("diagnostics:open-logs", async (event) => {
    assertTrustedDiagnosticsSender(event);
    return deps.openPath(deps.logDir);
  });
  deps.ipcMain.handle("diagnostics:set-enabled", (event, enabled: boolean) => {
    assertTrustedDiagnosticsSender(event);
    persistDiagnosticsChoice(deps.userDataDir, enabled);
    deps.setLogger(enabled ? deps.createLogger(deps.logDir) : null);
  });
}
