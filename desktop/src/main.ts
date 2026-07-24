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

import { Menu, app, BrowserWindow, dialog, ipcMain, screen, shell } from "electron";
import { autoUpdater } from "electron-updater";

import { createAppController } from "./appController";
import { LOCKFILE_NAME, QUIT_TIMEOUT_MS, baseUrl, isBackendRetryUrl, resolveBackendExe } from "./config";
import { patchConsoleForDiagnostics, registerDiagnosticsIpcHandlers } from "./diagnostics";
import {
  buildApplicationMenuTemplate,
  buildContextMenuTemplate,
} from "./menu";
import { findFreePort, runtimeDeps } from "./runtime";
import { getOrCreateSecretKey, regenerateSecretKey } from "./secretKey";
import { applyUserDataOverride } from "./userDataOverride";
import { readWindowState } from "./windowState";
import {
  createWindowStatePersister,
  editContextFromParams,
  handleAppCommand,
  navFor,
} from "./windowManager";
import { PersistentLogger, diagnosticsWereEnabled } from "./persistentLogger";
import {
  registerProcessFailureHandlers,
  registerRendererFailureHandler,
  type FailureUi,
} from "./failureHandling";

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
let persistentLogger: PersistentLogger | null = null;
let quitting = false;

const IS_MAC = process.platform === "darwin";

applyUserDataOverride(app, process.env.STL_STUDIO_USER_DATA_DIR);

const userDataDir = app.getPath("userData");
const logDir = join(userDataDir, "logs");
if (diagnosticsWereEnabled(userDataDir)) {
  try {
    persistentLogger = new PersistentLogger(logDir);
  } catch (error) {
    console.error("Could not initialize persistent desktop diagnostics", error);
  }
}

patchConsoleForDiagnostics(console, (level, values) => persistentLogger?.write(level, values));

registerDiagnosticsIpcHandlers({
  ipcMain,
  logDir,
  userDataDir,
  openPath: (path) => shell.openPath(path),
  createLogger: (directory) => new PersistentLogger(directory),
  setLogger: (logger) => {
    persistentLogger = logger;
  },
});

function startupLog(checkpoint: string): void {
  console.log(`[startup] ${checkpoint}`);
}

const appController = createAppController<BrowserWindow>({
  userDataDir,
  logDir,
  appVersion: app.getVersion(),
  isPackaged: app.isPackaged,
  platform: process.platform,
  env: process.env,
  resolveBackendExePath: () =>
    resolveBackendExe({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, repoRoot: REPO_ROOT }),
  createSidecarDeps: () =>
    runtimeDeps(userDataDir, LOCKFILE_NAME, (level, values) => persistentLogger?.write(level, values)),
  findFreePort,
  backendBaseUrl: (port) => baseUrl(port),
  getOrCreateSecretKey: (dir) => getOrCreateSecretKey(dir),
  regenerateSecretKeyFile: (dir) => regenerateSecretKey(dir),
  autoUpdaterAdapter: autoUpdater,
  setUpdateFeedUrl: (url) => autoUpdater.setFeedURL({ provider: "generic", url }),
  fetchJson: async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`settings request returned ${response.status}`);
    return response.json();
  },
  showErrorBox: (title, content) => dialog.showErrorBox(title, content),
  showMessageBox: (win, opts) => (win ? dialog.showMessageBox(win, opts) : dialog.showMessageBox(opts)),
  showKeyRevealWindow: (key) => showKeyRevealWindow(key),
  loadPlaceholderPage: (win) => win.loadFile(PLACEHOLDER_HTML),
  loadSplashPage: (win) => win.loadFile(SPLASH_HTML),
  quitApp: () => app.quit(),
  now: () => Date.now(),
  log: (message) => console.log(message),
});

const failureUi: FailureUi = {
  log(message, error) {
    console.error(`[failure] ${message}`, error ?? "");
  },
  async showRendererFailure(detail) {
    const { response } = await dialog.showMessageBox({
      type: "error",
      buttons: ["Reload STL Studio", "Quit"],
      defaultId: 0,
      cancelId: 1,
      title: "STL Studio stopped responding",
      message: "The application window closed unexpectedly",
      detail: `${detail}\n\nReload the window to recover. Saved catalog data is unchanged.`,
    });
    return response === 0 ? "reload" : "quit";
  },
  async showMainFailure(detail) {
    // showMessageBox (not showErrorBox) because the dedupe guard in
    // registerProcessFailureHandlers needs a promise that resolves on
    // dismissal (STUDIO-339) — showErrorBox is fire-and-forget and void.
    await dialog.showMessageBox({
      type: "error",
      buttons: ["OK"],
      defaultId: 0,
      title: "STL Studio encountered an internal error",
      message: "STL Studio encountered an internal error",
      detail: `${detail}\n\nClose and reopen STL Studio if the application no longer responds.`,
    });
  },
  quit() {
    app.quit();
  },
};

registerProcessFailureHandlers(process, failureUi);

startupLog("main-loaded");

/** Install our custom application menu (no Edit menu). Navigation acts on the
 *  focused window, so this is built once and never needs rebuilding. */
function installApplicationMenu(): void {
  const nav = navFor(() => BrowserWindow.getFocusedWindow()?.webContents);
  Menu.setApplicationMenu(
    Menu.buildFromTemplate(
      buildApplicationMenuTemplate(nav, {
        isMac: IS_MAC,
        onRegenerateKey: () => {
          if (mainWindow) void appController.regenerateEncryptionKey(mainWindow);
        },
        onCheckForUpdates: () => appController.checkForUpdatesManually(),
      }),
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

function createWindow(): BrowserWindow {
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
      preload: join(__dirname, "preload.js"),
    },
  });
  if (savedState.isMaximized) {
    win.maximize();
  }
  // Show the branded splash immediately (shown once it paints) so the app never
  // looks hung while the backend boots; bootBackendAndLoad swaps to the app.
  win.once("ready-to-show", () => win.show());
  void win.loadFile(SPLASH_HTML);
  registerRendererFailureHandler(win, failureUi);

  win.webContents.on("will-navigate", (event, url) => {
    if (!isBackendRetryUrl(url)) return;
    event.preventDefault();
    void win.loadFile(SPLASH_HTML).then(() => appController.bootBackendAndLoad(win));
  });

  // Right-click context menu: Back/Forward/Reload + clipboard when relevant.
  win.webContents.on("context-menu", (_event, params) => {
    const template = buildContextMenuTemplate(navFor(() => win.webContents), editContextFromParams(params));
    Menu.buildFromTemplate(template).popup({ window: win });
  });

  // Mouse back/forward buttons.
  win.on("app-command", (_event, command) => {
    handleAppCommand(command, win.webContents.navigationHistory);
  });

  const windowStatePersister = createWindowStatePersister({
    userDataDir,
    getState: () => ({ bounds: win.getNormalBounds(), isMaximized: win.isMaximized() }),
    delayMs: WINDOW_STATE_SAVE_DELAY_MS,
    onError: (error) => console.warn("Failed to save window state", error),
  });

  win.on("resize", () => windowStatePersister.schedule());
  win.on("move", () => windowStatePersister.schedule());
  win.on("close", () => windowStatePersister.flush());

  return win;
}

// Single-instance lock: a second launch hands focus to the running window
// instead of spawning a rival backend and a duplicate window.
const gotLock = app.requestSingleInstanceLock();
startupLog(`single-instance-lock=${gotLock ? "acquired" : "denied"}`);
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
    startupLog(`ready userData=${app.getPath("userData")}`);
    installApplicationMenu();
    mainWindow = createWindow();
    startupLog("window-created");
    await appController.bootBackendAndLoad(mainWindow);

    app.on("activate", async () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        mainWindow = createWindow();
        await appController.bootBackendAndLoad(mainWindow);
      }
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });

  // Terminate the sidecar before the process exits. The `quitting` guard
  // keeps this idempotent — app.quit() re-fires before-quit, and without it
  // this handler would loop forever.
  app.on("before-quit", async (event) => {
    if (quitting) return;
    quitting = true;
    event.preventDefault();
    // Buffered log lines (STUDIO-342) must land before exit, or the last
    // moments before a crash/quit — often the most useful part — are lost.
    await persistentLogger?.flush();
    // Belt-and-braces: killTree already caps itself at SHUTDOWN_GRACE_MS, but
    // this outer race means quit still proceeds even if something else in
    // stopOwnedSidecar hangs. Without it, quitting is already true, so a wedge
    // here would mean the only way out is Task Manager (STUDIO-340).
    await Promise.race([
      appController.stopOwnedSidecar(),
      new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          console.error(
            `[shutdown] stopOwnedSidecar did not complete within ${QUIT_TIMEOUT_MS}ms; quitting anyway (STUDIO-340)`,
          );
          resolve();
        }, QUIT_TIMEOUT_MS);
        timer.unref?.();
      }),
    ]);
    app.quit();
  });
}
