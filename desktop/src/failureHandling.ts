import type { BrowserWindow } from "electron";

type ProcessFailureSource = {
  on(event: "uncaughtException", listener: (error: Error) => void): unknown;
  on(event: "unhandledRejection", listener: (reason: unknown) => void): unknown;
};

export type FailureUi = {
  log(message: string, error?: unknown): void;
  showRendererFailure(detail: string): Promise<"reload" | "quit">;
  showMainFailure(detail: string): Promise<void>;
  quit(): void;
};

export function failureDetail(value: unknown): string {
  if (value instanceof Error) return value.stack || value.message;
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function registerProcessFailureHandlers(source: ProcessFailureSource, ui: FailureUi): void {
  // Mirrors registerRendererFailureHandler's recoveryVisible guard: a repeating
  // failure (interval, retry loop, stream error handler) must not stack modal
  // dialogs faster than the user can dismiss them (STUDIO-339). Logging stays
  // unthrottled — only the dialog is suppressed while one is already showing.
  let showingMainFailure = false;
  function report(logMessage: string, value: unknown): void {
    const detail = failureDetail(value);
    ui.log(logMessage, value);
    if (showingMainFailure) return;
    showingMainFailure = true;
    // catch + finally, not just then: a rejected showMainFailure (dialog API
    // itself throwing) must still clear the guard, or every subsequent
    // failure goes dialog-less — and the rejection must not escape as an
    // unhandled promise rejection back into this same handler.
    void ui.showMainFailure(detail)
      .catch(() => {})
      .finally(() => {
        showingMainFailure = false;
      });
  }
  source.on("uncaughtException", (error) => {
    report("Uncaught Electron main-process exception", error);
  });
  source.on("unhandledRejection", (reason) => {
    report("Unhandled Electron main-process promise rejection", reason);
  });
}

export function registerRendererFailureHandler(win: BrowserWindow, ui: FailureUi): void {
  let recoveryVisible = false;
  win.webContents.on("render-process-gone", (_event, details) => {
    if (recoveryVisible || details.reason === "clean-exit") return;
    recoveryVisible = true;
    const detail = `The renderer stopped (${details.reason}, exit code ${details.exitCode}).`;
    ui.log(detail);
    void ui.showRendererFailure(detail).then((action) => {
      recoveryVisible = false;
      if (action === "reload" && !win.isDestroyed()) {
        win.webContents.reload();
      } else if (action === "quit") {
        ui.quit();
      }
    });
  });
}
