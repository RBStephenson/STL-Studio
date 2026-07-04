/**
 * Electron main process — Phase 1 (STUDIO-71).
 *
 * Owns the Python backend as a sidecar child process: on startup it reaps any
 * orphan from a crashed prior run, spawns the backend exe, polls `/api/health`
 * until ready, then points the window at localhost. On quit it terminates the
 * sidecar. A single-instance lock focuses the existing window on a second launch.
 *
 * Port is FIXED at 8484 this phase; the backend gains `--port` in Phase 2, at
 * which point the port here becomes an OS-assigned free port (see config.ts).
 *
 * Ref: docs/plans/528-pywebview-to-electron.md,
 *      docs/plans/528-phase1-sidecar.md
 */
import { join } from "node:path";

import { app, BrowserWindow, dialog } from "electron";

import { BACKEND_PORT, LOCKFILE_NAME, baseUrl, resolveBackendExe } from "./config";
import { runtimeDeps } from "./runtime";
import { SidecarStartError, startSidecar, stopSidecar } from "./sidecar";
import type { SidecarDeps, SidecarProcess } from "./sidecar";

const PLACEHOLDER_HTML = join(__dirname, "..", "index.html");

// Repo root during dev: desktop/dist/main.js -> up two levels. Used only to
// resolve the dev backend-exe fallback; packaged resolution arrives in Phase 3.
const REPO_ROOT = join(__dirname, "..", "..");

let mainWindow: BrowserWindow | null = null;
let sidecar: SidecarProcess | null = null;
let deps: SidecarDeps | null = null;

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    title: "STL Studio",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.once("ready-to-show", () => win.show());
  return win;
}

/** Spawn the backend, wait for health, and load it — or show an error dialog and
 *  fall back to the placeholder page so the window is never blank-and-silent. */
async function bootBackendAndLoad(win: BrowserWindow): Promise<void> {
  deps = runtimeDeps(app.getPath("userData"), LOCKFILE_NAME);
  const exePath = resolveBackendExe(REPO_ROOT);
  try {
    const result = await startSidecar(deps, {
      exePath,
      // Phase 2: pass ["--port", String(port)] once the backend honours it.
      args: [],
      port: BACKEND_PORT,
    });
    sidecar = result.proc;
    await win.loadURL(baseUrl(result.port));
  } catch (err) {
    const message =
      err instanceof SidecarStartError
        ? err.message
        : `Unexpected error starting the backend: ${String(err)}`;
    dialog.showErrorBox("STL Studio — backend failed to start", message);
    await win.loadFile(PLACEHOLDER_HTML);
  }
}

// Single-instance lock: a second launch hands focus to the running window
// instead of spawning a rival backend on the same fixed port.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    mainWindow = createWindow();
    await bootBackendAndLoad(mainWindow);

    app.on("activate", async () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        mainWindow = createWindow();
        await bootBackendAndLoad(mainWindow);
      }
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });

  // Terminate the sidecar before the process exits. `before-quit` covers the
  // normal path; the kill is idempotent so a double-fire is harmless.
  app.on("before-quit", async (event) => {
    if (sidecar && deps) {
      event.preventDefault();
      const proc = sidecar;
      const d = deps;
      sidecar = null;
      await stopSidecar(d, proc);
      app.quit();
    }
  });
}
