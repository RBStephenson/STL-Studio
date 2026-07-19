import { describe, expect, it, vi } from "vitest";
import { createAppController } from "./appController";
import type { AppControllerDeps, BrowserWindowLike, MessageBoxOptions, MessageBoxResult } from "./appController";
import type { SidecarDeps, SidecarProcess } from "./sidecar";
import type { UpdaterAdapter } from "./updater";

function fakeWin(): BrowserWindowLike & { loadURL: ReturnType<typeof vi.fn>; loadFile: ReturnType<typeof vi.fn> } {
  return {
    loadURL: vi.fn().mockResolvedValue(undefined),
    loadFile: vi.fn().mockResolvedValue(undefined),
    webContents: { navigationHistory: { clear: vi.fn() } },
    setProgressBar: vi.fn(),
  };
}

function fakeSidecarDeps(overrides: Partial<SidecarDeps> = {}): SidecarDeps {
  let clock = 0;
  return {
    spawn: (): SidecarProcess => ({ pid: 4242, on: vi.fn() }),
    probe: async () => true,
    killTree: async () => undefined,
    readLock: () => null,
    writeLock: () => undefined,
    clearLock: () => undefined,
    now: () => clock,
    // Advancing the clock inside sleep lets a probe-always-false loop (used to
    // simulate a backend that never becomes healthy) terminate on the
    // timeout without a real 30s wait — see sidecar.test.ts's makeDeps.
    sleep: async (ms) => {
      clock += ms;
    },
    log: () => undefined,
    ...overrides,
  };
}

type Listener = (...args: never[]) => void;

function fakeUpdaterAdapter(): UpdaterAdapter & { listeners: Map<string, Listener> } {
  const listeners = new Map<string, Listener>();
  return {
    autoDownload: true,
    autoInstallOnAppQuit: true,
    allowPrerelease: true,
    on(event: string, listener: Listener) {
      listeners.set(event, listener);
      return this;
    },
    checkForUpdates: vi.fn().mockResolvedValue(undefined),
    downloadUpdate: vi.fn().mockResolvedValue(undefined),
    quitAndInstall: vi.fn(),
    listeners,
  } as unknown as UpdaterAdapter & { listeners: Map<string, Listener> };
}

function harness(overrides: Partial<AppControllerDeps<BrowserWindowLike>> = {}) {
  const showMessageBox = vi.fn<
    (win: BrowserWindowLike | undefined, opts: MessageBoxOptions) => Promise<MessageBoxResult>
  >().mockResolvedValue({ response: 0 });
  const deps: AppControllerDeps<BrowserWindowLike> = {
    userDataDir: "/userdata",
    logDir: "/userdata/logs",
    appVersion: "1.2.3",
    isPackaged: true,
    platform: "win32",
    env: {},
    resolveBackendExePath: () => "/backend/stl-studio.exe",
    createSidecarDeps: () => fakeSidecarDeps(),
    findFreePort: vi.fn().mockResolvedValue(5555),
    backendBaseUrl: (port) => `http://127.0.0.1:${port}`,
    getOrCreateSecretKey: vi.fn().mockReturnValue({ key: "secret-key", isNew: false }),
    regenerateSecretKeyFile: vi.fn().mockReturnValue("new-secret-key"),
    autoUpdaterAdapter: fakeUpdaterAdapter(),
    setUpdateFeedUrl: vi.fn(),
    fetchJson: vi.fn().mockResolvedValue({ auto_update_enabled: true }),
    showErrorBox: vi.fn(),
    showMessageBox,
    showKeyRevealWindow: vi.fn(),
    loadPlaceholderPage: vi.fn().mockResolvedValue(undefined),
    log: vi.fn(),
    ...overrides,
  };
  const controller = createAppController(deps);
  return { controller, deps, showMessageBox };
}

describe("bootBackendAndLoad", () => {
  it("boots the sidecar and loads the backend URL on success", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();

    await controller.bootBackendAndLoad(win);

    expect(win.loadURL).toHaveBeenCalledWith("http://127.0.0.1:5555");
    expect(win.webContents.navigationHistory.clear).toHaveBeenCalledOnce();
    expect(deps.loadPlaceholderPage).not.toHaveBeenCalled();
    expect(deps.showErrorBox).not.toHaveBeenCalled();
  });

  it("falls back to the placeholder page and shows an error dialog when the sidecar never becomes healthy", async () => {
    const { controller, deps } = harness({
      createSidecarDeps: () => fakeSidecarDeps({ probe: async () => false }),
    });
    const win = fakeWin();

    await controller.bootBackendAndLoad(win);

    expect(win.loadURL).not.toHaveBeenCalled();
    expect(deps.loadPlaceholderPage).toHaveBeenCalledWith(win);
    expect(deps.showErrorBox).toHaveBeenCalledWith(
      "STL Studio — backend failed to start",
      expect.stringContaining("did not become healthy"),
    );
  });

  it("reveals the key window when the secret key is newly generated", async () => {
    const { controller, deps } = harness({
      getOrCreateSecretKey: vi.fn().mockReturnValue({ key: "fresh-key", isNew: true }),
    });
    const win = fakeWin();

    await controller.bootBackendAndLoad(win);

    expect(deps.showKeyRevealWindow).toHaveBeenCalledWith("fresh-key");
  });

  it("does not reveal the key window on a normal boot with an existing key", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();

    await controller.bootBackendAndLoad(win);

    expect(deps.showKeyRevealWindow).not.toHaveBeenCalled();
  });

  it("reveals the key window when forceReveal is set even with an existing key", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();

    await controller.bootBackendAndLoad(win, { forceReveal: true });

    expect(deps.showKeyRevealWindow).toHaveBeenCalledWith("secret-key");
  });

  it("ignores a concurrent boot call while one is already in flight", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();

    const first = controller.bootBackendAndLoad(win);
    await controller.bootBackendAndLoad(win);
    await first;

    expect(deps.findFreePort).toHaveBeenCalledTimes(1);
  });
});

describe("checkForUpdatesManually", () => {
  it("shows an error when the updater has not initialized yet", () => {
    const { controller, deps } = harness();
    controller.checkForUpdatesManually();
    expect(deps.showErrorBox).toHaveBeenCalledWith(
      "STL Studio updates",
      expect.stringContaining("still starting"),
    );
  });

  it("delegates to the update controller once initialized via a boot", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);

    (deps.showErrorBox as ReturnType<typeof vi.fn>).mockClear();
    controller.checkForUpdatesManually();

    expect(deps.showErrorBox).not.toHaveBeenCalled();
    expect(deps.autoUpdaterAdapter.checkForUpdates).toHaveBeenCalled();
  });
});

describe("initializeUpdater (via bootBackendAndLoad)", () => {
  it("reads the auto-update setting and treats enabled=true as an automatic check", async () => {
    const { controller, deps } = harness({ fetchJson: vi.fn().mockResolvedValue({ auto_update_enabled: true }) });
    await controller.bootBackendAndLoad(fakeWin());
    expect(deps.autoUpdaterAdapter.checkForUpdates).toHaveBeenCalled();
  });

  it("still checks (manual=false path) when the setting read fails, treating it as disabled", async () => {
    const { controller, deps } = harness({ fetchJson: vi.fn().mockRejectedValue(new Error("network down")) });
    await controller.bootBackendAndLoad(fakeWin());
    expect(deps.log).toHaveBeenCalledWith(expect.stringContaining("Could not read automatic-update setting"));
  });

  it("enables prereleases on the updater when allow_prerelease_updates is true", async () => {
    const { controller, deps } = harness({
      fetchJson: vi.fn().mockResolvedValue({ auto_update_enabled: true, allow_prerelease_updates: true }),
    });
    await controller.bootBackendAndLoad(fakeWin());
    expect(deps.autoUpdaterAdapter.allowPrerelease).toBe(true);
  });

  it("leaves prereleases off when the setting is absent", async () => {
    const { controller, deps } = harness({ fetchJson: vi.fn().mockResolvedValue({ auto_update_enabled: true }) });
    await controller.bootBackendAndLoad(fakeWin());
    expect(deps.autoUpdaterAdapter.allowPrerelease).toBe(false);
  });
});

describe("regenerateEncryptionKey", () => {
  it("regenerates the key, restarts the sidecar, and reveals the new key on confirm", async () => {
    const { controller, deps, showMessageBox } = harness();
    showMessageBox.mockResolvedValue({ response: 1 });
    const win = fakeWin();

    await controller.regenerateEncryptionKey(win);

    expect(deps.regenerateSecretKeyFile).toHaveBeenCalledWith("/userdata");
    expect(deps.showKeyRevealWindow).toHaveBeenCalledWith("secret-key");
  });

  it("does nothing when the user cancels the confirmation dialog", async () => {
    const { controller, deps, showMessageBox } = harness();
    showMessageBox.mockResolvedValue({ response: 0 });
    const win = fakeWin();

    await controller.regenerateEncryptionKey(win);

    expect(deps.regenerateSecretKeyFile).not.toHaveBeenCalled();
    expect(deps.findFreePort).not.toHaveBeenCalled();
  });
});

describe("update UI wiring (via emitted updater events)", () => {
  async function bootedHarness(overrides: Partial<AppControllerDeps<BrowserWindowLike>> = {}) {
    const h = harness(overrides);
    const win = fakeWin();
    await h.controller.bootBackendAndLoad(win);
    const listeners = (h.deps.autoUpdaterAdapter as unknown as { listeners: Map<string, (...a: never[]) => void> })
      .listeners;
    return { ...h, win, listeners };
  }

  it("confirmDownload prompts via showMessageBox and downloads on accept", async () => {
    const { deps, listeners, showMessageBox } = await bootedHarness();
    showMessageBox.mockResolvedValue({ response: 0 });

    listeners.get("update-available")?.({ version: "9.9.9" } as never);
    await Promise.resolve();
    await Promise.resolve();

    expect(showMessageBox).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ title: "STL Studio update available" }),
    );
    expect(deps.autoUpdaterAdapter.downloadUpdate).toHaveBeenCalled();
  });

  it("showCurrent shows the up-to-date dialog on a manual check with nothing available", async () => {
    const { deps, controller, listeners, showMessageBox } = await bootedHarness();
    controller.checkForUpdatesManually();
    listeners.get("update-not-available")?.(undefined as never);
    await Promise.resolve();

    expect(showMessageBox).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ message: "You're up to date" }),
    );
    expect(deps.showErrorBox).not.toHaveBeenCalled();
  });

  it("showProgress maps percent to the window's progress bar, and null clears it", async () => {
    const { win, listeners } = await bootedHarness();
    listeners.get("download-progress")?.({ percent: 42 } as never);
    expect(win.setProgressBar).toHaveBeenCalledWith(0.42);

    listeners.get("update-downloaded")?.({ version: "9.9.9" } as never);
    expect(win.setProgressBar).toHaveBeenCalledWith(-1);
  });

  it("confirmRestart stops the sidecar and installs on accept", async () => {
    const { deps, listeners, showMessageBox } = await bootedHarness();
    showMessageBox.mockResolvedValue({ response: 0 });

    listeners.get("update-downloaded")?.({ version: "9.9.9" } as never);
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));

    expect(deps.autoUpdaterAdapter.quitAndInstall).toHaveBeenCalledWith(false, true);
  });

  it("showError surfaces updater errors via showErrorBox", async () => {
    const { deps, listeners } = await bootedHarness();
    listeners.get("error")?.(new Error("network down") as never);
    expect(deps.showErrorBox).not.toHaveBeenCalled(); // not manual and not downloading: suppressed
  });

  it("smoke mode sets the feed URL and auto-accepts download/restart without prompting", async () => {
    const { deps, listeners, showMessageBox } = await bootedHarness({
      env: { STL_STUDIO_UPDATE_SMOKE: "1", STL_STUDIO_UPDATE_FEED_URL: "http://localhost:9999/feed" },
    });

    expect(deps.setUpdateFeedUrl).toHaveBeenCalledWith("http://localhost:9999/feed");

    listeners.get("update-available")?.({ version: "1.0.0" } as never);
    await Promise.resolve();
    await Promise.resolve();

    expect(showMessageBox).not.toHaveBeenCalled();
    expect(deps.autoUpdaterAdapter.downloadUpdate).toHaveBeenCalled();
  });
});

describe("stopOwnedSidecar", () => {
  it("is a no-op when no sidecar has been booted", async () => {
    const { controller } = harness();
    await expect(controller.stopOwnedSidecar()).resolves.toBeUndefined();
  });

  it("stops the sidecar started by bootBackendAndLoad", async () => {
    const killTree = vi.fn().mockResolvedValue(undefined);
    const { controller } = harness({ createSidecarDeps: () => fakeSidecarDeps({ killTree }) });
    await controller.bootBackendAndLoad(fakeWin());

    await controller.stopOwnedSidecar();

    expect(killTree).toHaveBeenCalledWith(4242);
  });
});
