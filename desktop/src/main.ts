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

import { Menu, app, BrowserWindow, dialog, screen } from "electron";
import type { WebContents } from "electron";

import { LOCKFILE_NAME, baseUrl, resolveBackendExe } from "./config";
import {
  buildApplicationMenuTemplate,
  buildContextMenuTemplate,
} from "./menu";
import type { NavTarget } from "./menu";
import { findFreePort, runtimeDeps } from "./runtime";
import { getOrCreateSecretKey, regenerateSecretKey } from "./secretKey";
import { SidecarStartError, startSidecar, stopSidecar } from "./sidecar";
import type { SidecarDeps, SidecarProcess } from "./sidecar";
import { readWindowState, saveWindowState } from "./windowState";

const PLACEHOLDER_HTML = join(__dirname, "..", "index.html");
const SPLASH_HTML = join(__dirname, "..", "splash.html");
const KEY_REVEAL_HTML = join(__dirname, "..", "keyReveal.html");
const APP_ICON = join(__dirname, "..", "resources", "stl_studio.ico");
// Matches splash.html's background so there's no white flash before it paints.
const WINDOW_BG = "#070b16";
const WINDOW_STATE_SAVE_DELAY_MS = 250;

// Repo root during dev: desktop/dist/main.js -> up two levels. Used only to
// resolve the dev backend-exe fallback; the packaged app resolves the sidecar
// from process.resourcesPath instead.
const REPO_ROOT = join(__dirname, "..", "..");

let mainWindow: BrowserWindow | null = null;
let sidecar: SidecarProcess | null = null;
let deps: SidecarDeps | null = null;
let windowStateSaveTimer: NodeJS.Timeout | null = null;

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
    Menu.buildFromTemplate(
      buildApplicationMenuTemplate(nav, { isMac: IS_MAC, onRegenerateKey: regenerateEncryptionKey }),
    ),
  );
}

/** A small non-modal window showing the encryption key once, with a Copy
 *  button. Used both on first-ever generation and after a manual regenerate
 *  (STUDIO-147). The key is passed via query string — this window never talks
 *  to the backend, so there's no network exposure of the key. */
function showKeyRevealWindow(key: string): void {
  const win = new BrowserWindow({
    width: 560,
    height: 400,
    resizable: false,
    minimizable: false,
    maximizable: false,
    autoHideMenuBar: true,
    parent: mainWindow ?? undefined,
    title: "STL Studio — encryption key",
    icon: APP_ICON,
    backgroundColor: WINDOW_BG,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // The app menu (installApplicationMenu) is process-global in Electron, not
  // per-window — without this the reveal window inherits File/Navigate/View/
  // Window and its content gets clipped by the extra bar height.
  win.setMenu(null);
  void win.loadFile(KEY_REVEAL_HTML, { query: { key } });
}

/** Warn, generate a fresh key, restart the sidecar so the backend picks it up
 *  (secrets.py caches its Fernet instance for the process lifetime), and show
 *  the new key once. Regenerating invalidates every currently-stored
 *  encrypted secret (AI/Cults3D/MMF API keys) — decrypt failures are treated
 *  as "unset" by the backend, so the user simply re-enters them. */
async function regenerateEncryptionKey(): Promise<void> {
  if (!mainWindow) {
    return;
  }
  const { response } = await dialog.showMessageBox(mainWindow, {
    type: "warning",
    buttons: ["Cancel", "Regenerate"],
    defaultId: 0,
    cancelId: 0,
    title: "Regenerate encryption key?",
    message: "This will invalidate all saved API keys",
    detail:
      "Your AI, Cults3D, and MyMiniFactory API keys are encrypted with the current key and will stop decrypting once it's replaced. You'll need to re-enter them. This cannot be undone.",
  });
  if (response !== 1) {
    return;
  }
  regenerateSecretKey(app.getPath("userData"));
  if (sidecar && deps) {
    await stopSidecar(deps, sidecar);
    sidecar = null;
  }
  await bootBackendAndLoad(mainWindow, { forceReveal: true });
}

function createWindow(): BrowserWindow {
  const userDataDir = app.getPath("userData");
  const savedState = readWindowState(userDataDir, screen.getAllDisplays());
  const win = new BrowserWindow({
    ...savedState.bounds,
    show: false,
    title: "STL Studio",
    icon: APP_ICON,
    backgroundColor: WINDOW_BG,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  if (savedState.isMaximized) {
    win.maximize();
  }
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

  const saveCurrentWindowState = (): void => {
    try {
      saveWindowState(userDataDir, {
        bounds: win.getNormalBounds(),
        isMaximized: win.isMaximized(),
      });
    } catch (err) {
      console.warn("Failed to save window state", err);
    }
  };

  const persistWindowState = (): void => {
    if (windowStateSaveTimer) {
      clearTimeout(windowStateSaveTimer);
    }
    windowStateSaveTimer = setTimeout(() => {
      windowStateSaveTimer = null;
      saveCurrentWindowState();
    }, WINDOW_STATE_SAVE_DELAY_MS);
  };

  win.on("resize", persistWindowState);
  win.on("move", persistWindowState);
  win.on("close", () => {
    if (windowStateSaveTimer) {
      clearTimeout(windowStateSaveTimer);
      windowStateSaveTimer = null;
    }
    saveCurrentWindowState();
  });

  return win;
}

/** Spawn the backend, wait for health, and load it — or show an error dialog and
 *  fall back to the placeholder page so the window is never blank-and-silent.
 *  Resolves (generating on first run) the Fernet key the backend needs to
 *  encrypt/decrypt saved API keys and injects it as STL_SECRET_KEY (STUDIO-147).
 *  `forceReveal` shows the one-time key window even when the key already
 *  existed on disk — used after a manual regenerate. */
async function bootBackendAndLoad(
  win: BrowserWindow,
  opts: { forceReveal?: boolean } = {},
): Promise<void> {
  deps = runtimeDeps(app.getPath("userData"), LOCKFILE_NAME);
  const exePath = resolveBackendExe({
    packaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    repoRoot: REPO_ROOT,
  });
  const secretKey = getOrCreateSecretKey(app.getPath("userData"));
  try {
    const port = await findFreePort();
    const result = await startSidecar(deps, {
      exePath,
      args: ["--port", String(port)],
      env: { STL_SECRET_KEY: secretKey.key },
      port,
    });
    sidecar = result.proc;
    // Swap the splash for the app, then drop the splash from history so Back
    // never returns to it.
    await win.loadURL(baseUrl(result.port));
    win.webContents.navigationHistory.clear();
    if (secretKey.isNew || opts.forceReveal) {
      showKeyRevealWindow(secretKey.key);
    }
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
