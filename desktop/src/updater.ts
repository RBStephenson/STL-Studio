/** Automatic-update orchestration kept behind small injected boundaries so the
 * Electron event flow can be tested without contacting GitHub or loading the
 * Electron runtime. */

export interface UpdateInfo {
  version: string;
}

export interface DownloadProgress {
  percent: number;
}

export interface UpdaterAdapter {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  allowPrerelease: boolean;
  on(event: "checking-for-update", listener: () => void): this;
  on(event: "update-available" | "update-not-available" | "update-downloaded", listener: (info: UpdateInfo) => void): this;
  on(event: "download-progress", listener: (progress: DownloadProgress) => void): this;
  on(event: "error", listener: (error: Error) => void): this;
  checkForUpdates(): Promise<unknown>;
  downloadUpdate(): Promise<unknown>;
  quitAndInstall(isSilent?: boolean, isForceRunAfter?: boolean): void;
}

export interface UpdateUi {
  confirmDownload(version: string): Promise<boolean>;
  showCurrent(version: string): Promise<void>;
  showError(message: string): void;
  showProgress(percent: number | null): void;
  confirmRestart(version: string): Promise<boolean>;
}

export interface UpdateControllerOptions {
  updater: UpdaterAdapter;
  ui: UpdateUi;
  currentVersion: string;
  enabled: boolean;
  supported: boolean;
  stopApplication: () => Promise<void>;
  log: (message: string) => void;
}

export interface UpdateController {
  check(manual?: boolean): Promise<void>;
}

export function createUpdateController(options: UpdateControllerOptions): UpdateController {
  const { updater, ui } = options;
  let manualCheck = false;
  let downloading = false;

  updater.autoDownload = false;
  updater.autoInstallOnAppQuit = false;
  updater.allowPrerelease = false;

  updater.on("update-available", (info) => {
    void (async () => {
      try {
        options.log(`update ${info.version} available`);
        if (!(await ui.confirmDownload(info.version))) return;
        downloading = true;
        await updater.downloadUpdate();
      } catch (error) {
        downloading = false;
        ui.showProgress(null);
        ui.showError(`Could not download the update: ${String(error)}`);
      }
    })();
  });

  updater.on("update-not-available", () => {
    options.log("application is up to date");
    if (manualCheck) {
      void ui.showCurrent(options.currentVersion).catch((error) =>
        options.log(`could not show update status: ${String(error)}`));
    }
    manualCheck = false;
  });

  updater.on("download-progress", ({ percent }) => {
    downloading = true;
    ui.showProgress(Math.max(0, Math.min(100, percent)));
  });

  updater.on("update-downloaded", (info) => {
    downloading = false;
    ui.showProgress(null);
    void (async () => {
      try {
        if (!(await ui.confirmRestart(info.version))) return;
        await options.stopApplication();
        updater.quitAndInstall(false, true);
      } catch (error) {
        ui.showError(`Could not prepare the update for installation: ${String(error)}`);
      }
    })();
  });

  updater.on("error", (error) => {
    options.log(`update error: ${error.message}`);
    if (manualCheck || downloading) ui.showError(error.message);
    manualCheck = false;
    downloading = false;
    ui.showProgress(null);
  });

  return {
    async check(manual = false): Promise<void> {
      if (!options.supported) {
        if (manual) ui.showError("Updates are available only in the installed Windows app.");
        return;
      }
      if (!manual && !options.enabled) {
        options.log("automatic update check disabled by user setting");
        return;
      }
      manualCheck = manual;
      try {
        await updater.checkForUpdates();
      } catch (error) {
        manualCheck = false;
        if (manual) ui.showError(`Could not check for updates: ${String(error)}`);
      }
    },
  };
}

export async function readAutoUpdateEnabled(
  backendUrl: string,
  fetchJson: (url: string) => Promise<unknown>,
): Promise<boolean> {
  const value = await fetchJson(`${backendUrl}/api/settings`);
  return typeof value === "object" && value !== null &&
    (value as { auto_update_enabled?: unknown }).auto_update_enabled === true;
}
