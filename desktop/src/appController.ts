/**
 * Backend/updater orchestration extracted from main.ts (STUDIO-257).
 *
 * Owns the mutable state that used to live as module-scope `let`s in main.ts
 * (the running sidecar, its deps, the update controller, a boot-in-progress
 * flag) inside a factory closure instead, so it can be constructed fresh per
 * test with fully injected boundaries — no real Electron runtime, filesystem,
 * or network required to exercise the boot/failure/update-init branches.
 */
import { MAX_SIDECAR_RESTARTS, SIDECAR_RESTART_WINDOW_MS } from "./config";
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
  /** True once Electron has torn the window down. Every boot step that touches
   *  the window must check this first — a destroyed window throws synchronously
   *  on any access (STUDIO-337). */
  isDestroyed(): boolean;
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
  /** Show the branded splash again, used while a crashed backend restarts so the
   *  dead page isn't left on screen for the length of a boot (STUDIO-338). */
  loadSplashPage: (win: Win) => Promise<void>;
  /** Quit the application — the "Quit" answer to the crash-recovery prompt. */
  quitApp: () => void;
  /** Wall clock, injected so the crash-loop window is testable without timers. */
  now: () => number;

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
  // Set while a stop we initiated is in flight, so a boot racing it knows the
  // backend went away because we killed it — not because it failed to start —
  // and skips the startup-error dialog. Cleared at the top of every boot so
  // stop-then-boot flows (regenerateEncryptionKey) still work.
  let stopRequested = false;
  // The window the last boot targeted. Crash recovery happens outside any call
  // to bootBackendAndLoad, so it has no other way to reach the window.
  let lastWindow: Win | null = null;
  // One crash prompt at a time — a backend that dies repeatedly must not stack
  // dialogs (mirrors registerRendererFailureHandler's recoveryVisible).
  let recoveryVisible = false;
  // Timestamps of restarts we've attempted, pruned to the crash-loop window.
  let restartAttempts: number[] = [];

  async function stopOwnedSidecar(): Promise<void> {
    stopRequested = true;
    if (!sidecar || !sidecarDeps) return;
    const proc = sidecar;
    const d = sidecarDeps;
    sidecar = null;
    await stopSidecar(d, proc);
  }

  /** True once the backend has been restarted too many times in quick
   *  succession — at that point restarting again just repeats the crash. */
  function inCrashLoop(): boolean {
    const cutoff = deps.now() - SIDECAR_RESTART_WINDOW_MS;
    restartAttempts = restartAttempts.filter((at) => at > cutoff);
    return restartAttempts.length >= MAX_SIDECAR_RESTARTS;
  }

  /** Best-effort recovery UI: the window may die at any point here, and a
   *  failure to render the fallback must never escape as an unhandled
   *  rejection (see STUDIO-337). */
  async function showRecoveryPage(win: Win): Promise<void> {
    try {
      await deps.loadPlaceholderPage(win);
    } catch (error) {
      deps.log(`[backend] could not show the recovery page: ${String(error)}`);
    }
  }

  /**
   * The backend died on its own after a successful boot. Offer a restart, or
   * quit — anything is better than leaving the renderer pointed at a port that
   * no longer answers, which is what happened before STUDIO-338.
   */
  async function handleUnexpectedExit(code: number | null): Promise<void> {
    const win = lastWindow;
    if (!win || win.isDestroyed() || recoveryVisible) return;
    recoveryVisible = true;
    try {
      deps.log(`[backend] exited unexpectedly with code ${code}`);
      if (inCrashLoop()) {
        deps.showErrorBox(
          "STL Studio — the backend keeps stopping",
          "The STL Studio backend has stopped several times in a row, so it will not be "
            + "restarted again automatically.\n\nYour saved catalog data is unchanged. Close and "
            + "reopen STL Studio to try again; if it keeps happening, enable support logs and "
            + "report the issue.",
        );
        await showRecoveryPage(win);
        return;
      }
      const { response } = await deps.showMessageBox(win, {
        type: "error",
        buttons: ["Restart backend", "Quit"],
        defaultId: 0,
        cancelId: 1,
        title: "STL Studio backend stopped",
        message: "The STL Studio backend stopped unexpectedly",
        detail:
          "Your saved catalog data is unchanged. Restart the backend to carry on working — "
          + "anything you had not yet saved may need to be entered again.",
      });
      if (response !== 0) {
        deps.quitApp();
        return;
      }
      restartAttempts.push(deps.now());
      if (win.isDestroyed()) return;
      try {
        await deps.loadSplashPage(win);
      } catch (error) {
        // Cosmetic only — the boot below is what matters.
        deps.log(`[backend] could not show the splash while restarting: ${String(error)}`);
      }
      await bootBackendAndLoad(win);
    } finally {
      recoveryVisible = false;
    }
  }

  /** Decides whether an exit was ours to expect. The sidecar module reports
   *  every exit; only this closure knows the surrounding lifecycle state. */
  function onSidecarExit(proc: SidecarProcess, code: number | null): void {
    // Belt and braces: an exit we asked for is already covered by the identity
    // check below, because stopOwnedSidecar clears `sidecar` before killing.
    // Kept so a future reordering there can't silently turn a deliberate stop
    // into a crash report.
    if (stopRequested) return;
    // Died before it ever became healthy: the health poll owns that failure and
    // already surfaces it, so handling it here too would double-report.
    if (backendBooting) return;
    // A process superseded by a later boot; its exit listener still fires when
    // we kill it during a restart. Only the process we currently own counts.
    if (proc !== sidecar) return;
    sidecar = null;
    void handleUnexpectedExit(code);
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
    stopRequested = false;
    lastWindow = win;
    // Either the app is quitting or the user closed the window: the boot has
    // nowhere to land, so bail without alarming anyone. Both are ordinary user
    // actions, not startup failures (STUDIO-336, STUDIO-337).
    const shouldAbandon = (): boolean => stopRequested || win.isDestroyed();
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
        // Take ownership at spawn time, not on success — see STUDIO-336.
        onSpawn: (proc) => {
          sidecar = proc;
        },
        onExit: onSidecarExit,
      });
      // A quit arriving during the health poll already terminated this process,
      // and a closed window has nothing to point at either way.
      if (shouldAbandon()) {
        deps.log("[startup] backend-boot-abandoned before load");
        return;
      }
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
      // startSidecar kills the process tree itself when the health poll times
      // out, so drop our (now dead) handle. Any other error leaves a live
      // backend we must keep owning so quit still terminates it.
      if (err instanceof SidecarStartError) {
        sidecar = null;
      }
      // Either we killed the backend ourselves (quit / key regenerate) or the
      // user closed the window mid-boot — in both cases `err` is a symptom of
      // that, not a startup failure, and there is no window left to show it in.
      if (shouldAbandon()) {
        deps.log(`[startup] backend-boot-abandoned: ${String(err)}`);
        return;
      }
      const failedToStart = err instanceof SidecarStartError;
      deps.showErrorBox(
        failedToStart
          ? "STL Studio — backend failed to start"
          : "STL Studio — could not open the app",
        failedToStart ? err.message : `Unexpected error starting the backend: ${String(err)}`,
      );
      // Last-resort UI. If this fails too there is nothing further to try, and
      // letting it reject would escape the catch and surface as an "internal
      // error" dialog on top of the one we just showed.
      try {
        await deps.loadPlaceholderPage(win);
      } catch (fallbackErr) {
        deps.log(`[startup] could not show the recovery page: ${String(fallbackErr)}`);
      }
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
