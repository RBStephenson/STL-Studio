/**
 * Electron main process.
 *
 * Owns the Python backend as a sidecar child process: on startup it reaps any
 * orphan from a crashed prior run, picks a free port, spawns the backend exe with
 * `--port`, polls `/api/health` until ready, then points the window at localhost.
 * On quit it terminates the sidecar. A single-instance lock focuses the existing
 * window on a second launch.
 *
 * Ref: docs/plans/528-pywebview-to-electron.md,
 *      docs/plans/528-phase1-sidecar.md
 */
import { join } from "node:path";

import { Menu, app, BrowserWindow, dialog } from "electron";
import type { WebContents } from "electron";

import { LOCKFILE_NAME, baseUrl, resolveBackendExe } from "./config";
import {
  buildApplicationMenuTemplate,
  buildContextMenuTemplate,
} from "./menu";
import type { NavTarget } from "./menu";
import { findFreePort, runtimeDeps } from "./runtime";
import { SidecarStartError, startSidecar, stopSidecar } from "./sidecar";
import type { SidecarDeps, SidecarProcess } from "./sidecar";

const PLACEHOLDER_HTML = join(__dirname, "..", "index.html");
const SPLASH_HTML = join(__dirname, "..", "splash.html");
const APP_ICON = join(__dirname, "..", "resources", "stl_studio.ico");
// Matches splash.html's background so there's no white flash before it paints.
const WINDOW_BG = "#070b16";

// Repo root during dev: desktop/dist/main.js -> up two levels. Used only to
// resolve the dev backend-exe fallback; the packaged app resolves the sidecar
// from process.resourcesPath instead.
const REPO_ROOT = join(__dirname, "..", "..");

let mainWindow: BrowserWindow | null = null;
let sidecar: SidecarProcess | null = null;
let deps: SidecarDeps | null = null;

const IS_MAC = process.platform === "darwin";

/** A NavTarget over a webContents' navigation history — drives both menus. */
function navFor(wc: WebContents): NavTarget {
  const history = wc.navigationHistory;
  return {
    canGoBack: () => history.canGoBack(),
    canGoForward: () => history.canGoForward(),
    goBack: () => history.goBack(),
    goForward: () => history.goForward(),
    reload: () => wc.reload(),
  };
}

/** Install our custom application menu (no Edit menu). Navigation acts on the
 *  focused window, so this is built once and never needs rebuilding. */
function installApplicationMenu(): void {
  const nav: NavTarget = {
    canGoBack: () => BrowserWindow.getFocusedWindow()?.webContents.navigationHistory.canGoBack() ?? false,
    canGoForward: () => BrowserWindow.getFocusedWindow()?.webContents.navigationHistory.canGoForward() ?? false,
    goBack: () => BrowserWindow.getFocusedWindow()?.webContents.navigationHistory.goBack(),
    goForward: () => BrowserWindow.getFocusedWindow()?.webContents.navigationHistory.goForward(),
    reload: () => BrowserWindow.getFocusedWindow()?.webContents.reload(),
  };
  Menu.setApplicationMenu(
    Menu.buildFromTemplate(buildApplicationMenuTemplate(nav, { isMac: IS_MAC })),
  );
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    title: "STL Studio",
    icon: APP_ICON,
    backgroundColor: WINDOW_BG,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // Show the branded splash immediately (shown once it paints) so the app never
  // looks hung while the backend boots; bootBackendAndLoad swaps to the app.
  win.once("ready-to-show", () => win.show());
  void win.loadFile(SPLASH_HTML);

  // Right-click context menu: Back/Forward/Reload + clipboard when relevant.
  win.webContents.on("context-menu", (_event, params) => {
    const template = buildContextMenuTemplate(navFor(win.webContents), {
      isEditable: params.isEditable,
      canCopy: params.editFlags.canCopy,
      canPaste: params.editFlags.canPaste,
    });
    Menu.buildFromTemplate(template).popup({ window: win });
  });

  // Mouse back/forward buttons.
  win.on("app-command", (_event, command) => {
    const history = win.webContents.navigationHistory;
    if (command === "browser-backward" && history.canGoBack()) {
      history.goBack();
    } else if (command === "browser-forward" && history.canGoForward()) {
      history.goForward();
    }
  });

  return win;
}

/** Spawn the backend, wait for health, and load it — or show an error dialog and
 *  fall back to the placeholder page so the window is never blank-and-silent. */
async function bootBackendAndLoad(win: BrowserWindow): Promise<void> {
  deps = runtimeDeps(app.getPath("userData"), LOCKFILE_NAME);
  const exePath = resolveBackendExe({
    packaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    repoRoot: REPO_ROOT,
  });
  try {
    const port = await findFreePort();
    const result = await startSidecar(deps, {
      exePath,
      args: ["--port", String(port)],
      port,
    });
    sidecar = result.proc;
    // Swap the splash for the app, then drop the splash from history so Back
    // never returns to it.
    await win.loadURL(baseUrl(result.port));
    win.webContents.navigationHistory.clear();
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
// instead of spawning a rival backend and a duplicate window.
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
    installApplicationMenu();
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
