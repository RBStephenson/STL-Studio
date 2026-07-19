/**
 * Backend/updater orchestration extracted from main.ts (STUDIO-257).
 *
 * Owns the mutable state that used to live as module-scope `let`s in main.ts
 * (the running sidecar, its deps, the update controller, a boot-in-progress
 * flag) inside a factory closure instead, so it can be constructed fresh per
 * test with fully injected boundaries — no real Electron runtime, filesystem,
 * or network required to exercise the boot/failure/update-init branches.
 */
import { readAutoUpdateEnabled, readAllowPrereleaseUpdates, createUpdateController } from "./updater";
import type { UpdateController, UpdaterAdapter, UpdateUi } from "./updater";
import { readUpdateSmokeConfig } from "./updateSmoke";
import { SidecarStartError, startSidecar, stopSidecar } from "./sidecar";
import type { SidecarDeps, SidecarProcess } from "./sidecar";
import type { ResolvedSecretKey } from "./secretKey";

/** The subset of BrowserWindow this module touches, kept narrow so tests
 *  don't need a real Electron window. */
export interface BrowserWindowLike {
  loadURL(url: string): Promise<void>;
  loadFile(path: string): Promise<void>;
  webContents: { navigationHistory: { clear(): void } };
  setProgressBar(value: number): void;
}

export interface MessageBoxResult {
  response: number;
}

export interface MessageBoxOptions {
  type: "info" | "warning" | "error";
  buttons: string[];
  defaultId?: number;
  cancelId?: number;
  title: string;
  message: string;
  detail?: string;
}

export interface AppControllerDeps<Win extends BrowserWindowLike = BrowserWindowLike> {
  userDataDir: string;
  logDir: string;
  appVersion: string;
  isPackaged: boolean;
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;

  resolveBackendExePath: () => string;
  createSidecarDeps: () => SidecarDeps;
  findFreePort: () => Promise<number>;
  backendBaseUrl: (port: number) => string;
  getOrCreateSecretKey: (userDataDir: string) => ResolvedSecretKey;
  regenerateSecretKeyFile: (userDataDir: string) => string;

  autoUpdaterAdapter: UpdaterAdapter;
  setUpdateFeedUrl: (url: string) => void;
  fetchJson: (url: string) => Promise<unknown>;

  showErrorBox: (title: string, content: string) => void;
  showMessageBox: (win: Win | undefined, opts: MessageBoxOptions) => Promise<MessageBoxResult>;
  showKeyRevealWindow: (key: string) => void;
  loadPlaceholderPage: (win: Win) => Promise<void>;

  log: (message: string) => void;
}

export interface AppController<Win extends BrowserWindowLike = BrowserWindowLike> {
  /** Spawn the backend, wait for health, and load it — or show an error
   *  dialog and fall back to the placeholder page. `forceReveal` shows the
   *  key window even when the key already existed (after a manual
   *  regenerate). */
  bootBackendAndLoad(win: Win, opts?: { forceReveal?: boolean }): Promise<void>;
  /** Terminate the currently-owned sidecar, if any. Safe to call when none is
   *  running. */
  stopOwnedSidecar(): Promise<void>;
  /** Manual "Check for Updates" menu action. Shows an error if the updater
   *  hasn't initialized yet (still mid-boot). */
  checkForUpdatesManually(): void;
  /** Regenerate the encryption key after user confirmation, restart the
   *  sidecar so the backend picks it up, and reveal the new key. No-ops (no
   *  dialog) if the user declines. */
  regenerateEncryptionKey(win: Win): Promise<void>;
}

export function createAppController<Win extends BrowserWindowLike>(
  deps: AppControllerDeps<Win>,
): AppController<Win> {
  let sidecar: SidecarProcess | null = null;
  let sidecarDeps: SidecarDeps | null = null;
  let updateController: UpdateController | null = null;
  let backendBooting = false;

  async function stopOwnedSidecar(): Promise<void> {
    if (!sidecar || !sidecarDeps) return;
    const proc = sidecar;
    const d = sidecarDeps;
    sidecar = null;
    await stopSidecar(d, proc);
  }

  async function initializeUpdater(win: Win, backendUrl: string): Promise<void> {
    if (updateController) return;
    const smoke = readUpdateSmokeConfig(deps.env);
    if (smoke) {
      deps.setUpdateFeedUrl(smoke.feedUrl);
      deps.log(`[updater-smoke] feed=${smoke.feedUrl}`);
    }
    let enabled = false;
    let allowPrerelease = false;
    try {
      enabled = await readAutoUpdateEnabled(backendUrl, deps.fetchJson);
      allowPrerelease = await readAllowPrereleaseUpdates(backendUrl, deps.fetchJson);
    } catch (error) {
      deps.log(`Could not read automatic-update setting; skipping startup check: ${String(error)}`);
    }

    const ui: UpdateUi = {
      async confirmDownload(version) {
        if (smoke) {
          deps.log(`[updater-smoke] accepting download ${version}`);
          return true;
        }
        const { response } = await deps.showMessageBox(win, {
          type: "info",
          buttons: ["Download", "Later"],
          defaultId: 0,
          cancelId: 1,
          title: "STL Studio update available",
          message: `STL Studio ${version} is available`,
          detail: "Download it in the background? You can keep using STL Studio while it downloads.",
        });
        return response === 0;
      },
      async showCurrent(version) {
        await deps.showMessageBox(win, {
          type: "info",
          buttons: ["OK"],
          title: "STL Studio updates",
          message: "You're up to date",
          detail: `STL Studio ${version} is the newest available version.`,
        });
      },
      showError(message) {
        deps.showErrorBox("STL Studio update failed", message);
      },
      showProgress(percent) {
        win.setProgressBar(percent === null ? -1 : percent / 100);
      },
      async confirmRestart(version) {
        if (smoke) {
          deps.log(`[updater-smoke] accepting restart ${version}`);
          return true;
        }
        const { response } = await deps.showMessageBox(win, {
          type: "info",
          buttons: ["Restart and Install", "Later"],
          defaultId: 0,
          cancelId: 1,
          title: "STL Studio update ready",
          message: `STL Studio ${version} is ready to install`,
          detail: "Restart now to finish the update, or keep working and install it later.",
        });
        return response === 0;
      },
    };

    updateController = createUpdateController({
      updater: deps.autoUpdaterAdapter,
      currentVersion: deps.appVersion,
      enabled: smoke ? true : enabled,
      // Smoke mode serves a specific candidate feed (which may be a prerelease
      // version) on loopback, so it must accept prereleases regardless of setting.
      allowPrerelease: smoke ? true : allowPrerelease,
      supported: deps.isPackaged && deps.platform === "win32",
      stopApplication: stopOwnedSidecar,
      log: (message) => deps.log(`[updater] ${message}`),
      ui,
    });
    void updateController.check();
  }

  function checkForUpdatesManually(): void {
    if (!updateController) {
      deps.showErrorBox(
        "STL Studio updates",
        "The backend is still starting. Try checking again in a moment.",
      );
      return;
    }
    void updateController.check(true);
  }

  async function bootBackendAndLoad(win: Win, opts: { forceReveal?: boolean } = {}): Promise<void> {
    if (backendBooting) return;
    deps.log("[startup] backend-boot-begin");
    backendBooting = true;
    sidecarDeps = deps.createSidecarDeps();
    const exePath = deps.resolveBackendExePath();
    const secretKey = deps.getOrCreateSecretKey(deps.userDataDir);
    try {
      const port = await deps.findFreePort();
      const result = await startSidecar(sidecarDeps, {
        exePath,
        args: ["--port", String(port)],
        env: {
          STL_SECRET_KEY: secretKey.key,
          STL_STUDIO_VERSION: deps.appVersion,
          DEPLOYMENT_MODE: "electron",
          STL_STUDIO_LOG_DIR: deps.logDir,
        },
        port,
      });
      sidecar = result.proc;
      const backendUrl = deps.backendBaseUrl(result.port);
      // Swap the splash for the app, then drop the splash from history so Back
      // never returns to it.
      await win.loadURL(backendUrl);
      win.webContents.navigationHistory.clear();
      await initializeUpdater(win, backendUrl);
      if (secretKey.isNew || opts.forceReveal) {
        deps.showKeyRevealWindow(secretKey.key);
      }
    } catch (err) {
      const message =
        err instanceof SidecarStartError
          ? err.message
          : `Unexpected error starting the backend: ${String(err)}`;
      deps.showErrorBox("STL Studio — backend failed to start", message);
      await deps.loadPlaceholderPage(win);
    } finally {
      backendBooting = false;
    }
  }

  async function regenerateEncryptionKey(win: Win): Promise<void> {
    const { response } = await deps.showMessageBox(win, {
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
    deps.regenerateSecretKeyFile(deps.userDataDir);
    await stopOwnedSidecar();
    await bootBackendAndLoad(win, { forceReveal: true });
  }

  return {
    bootBackendAndLoad,
    stopOwnedSidecar,
    checkForUpdatesManually,
    regenerateEncryptionKey,
  };
}
