import type { BrowserWindow } from "electron";

type ProcessFailureSource = {
  on(event: "uncaughtException", listener: (error: Error) => void): unknown;
  on(event: "unhandledRejection", listener: (reason: unknown) => void): unknown;
};

export type FailureUi = {
  log(message: string, error?: unknown): void;
  showRendererFailure(detail: string): Promise<"reload" | "quit">;
  showMainFailure(detail: string): void;
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
  source.on("uncaughtException", (error) => {
    const detail = failureDetail(error);
    ui.log("Uncaught Electron main-process exception", error);
    ui.showMainFailure(detail);
  });
  source.on("unhandledRejection", (reason) => {
    const detail = failureDetail(reason);
    ui.log("Unhandled Electron main-process promise rejection", reason);
    ui.showMainFailure(detail);
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
