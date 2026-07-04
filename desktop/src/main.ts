/**
 * Electron main process — Phase 0 skeleton (STUDIO-70).
 *
 * Boots a single BrowserWindow that loads a static placeholder page. There is
 * NO backend wiring yet: the Python sidecar spawn, health poll, and localhost
 * load arrive in Phase 1 (sidecar.ts). This file exists to prove the toolchain
 * — electron + electron-builder + tsc — builds and launches a window.
 *
 * Ref: docs/plans/528-pywebview-to-electron.md (Phase 0),
 *      docs/plans/528-phase0-electron-skeleton.md
 */
import { join } from "node:path";

import { app, BrowserWindow } from "electron";

const PLACEHOLDER_HTML = join(__dirname, "..", "index.html");

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    title: "STL Studio",
    webPreferences: {
      // Phase 0 loads only a bundled static file. No preload/IPC surface is
      // needed until the sidecar wiring lands, so keep the renderer locked down.
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Defer the reveal until the page is painted to avoid a white flash.
  win.once("ready-to-show", () => win.show());
  void win.loadFile(PLACEHOLDER_HTML);
}

app.whenReady().then(() => {
  createWindow();

  // macOS convention: re-open a window when the dock icon is clicked and none
  // are open. Harmless on Windows (v1's only target) and keeps the lifecycle
  // idiomatic for later phases.
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when every window is closed, except on macOS where apps typically stay
// resident until the user explicitly quits.
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
