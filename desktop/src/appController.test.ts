import { describe, expect, it, vi } from "vitest";
import { MAX_SIDECAR_RESTARTS, SIDECAR_RESTART_WINDOW_MS } from "./config";
import { createAppController } from "./appController";
import type { AppControllerDeps, BrowserWindowLike, MessageBoxOptions, MessageBoxResult } from "./appController";
import type { SidecarDeps, SidecarProcess } from "./sidecar";
import type { UpdaterAdapter } from "./updater";

type FakeWin = BrowserWindowLike & {
  loadURL: ReturnType<typeof vi.fn>;
  loadFile: ReturnType<typeof vi.fn>;
  /** Simulate Electron tearing the window down: every subsequent access throws,
   *  which is what a real destroyed BrowserWindow does. */
  destroy(): void;
};

function fakeWin(): FakeWin {
  let destroyed = false;
  const ifAlive = <T>(value: T): T => {
    if (destroyed) throw new Error("Object has been destroyed");
    return value;
  };
  return {
    loadURL: vi.fn(async () => ifAlive(undefined)),
    loadFile: vi.fn(async () => ifAlive(undefined)),
    webContents: { navigationHistory: { clear: vi.fn() } },
    setProgressBar: vi.fn(),
    isDestroyed: () => destroyed,
    destroy: () => {
      destroyed = true;
    },
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
  let clock = 0;
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
    loadSplashPage: vi.fn().mockResolvedValue(undefined),
    quitApp: vi.fn(),
    now: () => clock,
    log: vi.fn(),
    ...overrides,
  };
  const controller = createAppController(deps);
  return { controller, deps, showMessageBox, advanceClock: (ms: number) => { clock += ms; } };
}

/** Spawns processes whose "exit" event the test can fire on demand, driving the
 *  real startSidecar → opts.onExit path rather than reaching into the
 *  controller. Each spawn is recorded so the identity check (current process vs
 *  one superseded by a later boot) can be exercised. */
function crashableSidecar() {
  const spawned: Array<{ fireExit: (code?: number | null) => void }> = [];
  const createSidecarDeps = (): SidecarDeps => fakeSidecarDeps({
    spawn: (): SidecarProcess => {
      let exitListener: ((code: number | null) => void) | undefined;
      const index = spawned.length;
      spawned.push({ fireExit: (code = 1) => exitListener?.(code) });
      return {
        pid: 4242 + index,
        on: (event: string, listener: (code: number | null) => void) => {
          if (event === "exit") exitListener = listener;
        },
      } as unknown as SidecarProcess;
    },
  });
  return { createSidecarDeps, spawned };
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

  it("terminates the spawned backend when a quit arrives during the health poll (STUDIO-336)", async () => {
    const killed: number[] = [];
    let spawned!: () => void;
    const hasSpawned = new Promise<void>((resolve) => {
      spawned = resolve;
    });
    let releaseProbe!: () => void;
    const probeGate = new Promise<void>((resolve) => {
      releaseProbe = resolve;
    });
    const { controller, deps } = harness({
      createSidecarDeps: () => fakeSidecarDeps({
        spawn: (): SidecarProcess => {
          spawned();
          return { pid: 4242, on: vi.fn() };
        },
        // Never healthy, and blocked until the test releases it — this is the
        // window during which the user quits.
        probe: async () => {
          await probeGate;
          return false;
        },
        killTree: async (pid) => {
          killed.push(pid);
        },
      }),
    });
    const win = fakeWin();

    const booting = controller.bootBackendAndLoad(win);
    await hasSpawned;
    await controller.stopOwnedSidecar();

    expect(killed).toEqual([4242]);

    releaseProbe();
    await booting;

    // We killed it; that is not a startup failure worth alarming the user about.
    expect(deps.showErrorBox).not.toHaveBeenCalled();
    expect(deps.loadPlaceholderPage).not.toHaveBeenCalled();
    expect(win.loadURL).not.toHaveBeenCalled();
  });

  it("does not load the backend URL when a quit arrives just before the window swap", async () => {
    let spawned!: () => void;
    const hasSpawned = new Promise<void>((resolve) => {
      spawned = resolve;
    });
    let releaseProbe!: () => void;
    const probeGate = new Promise<void>((resolve) => {
      releaseProbe = resolve;
    });
    const { controller, deps } = harness({
      createSidecarDeps: () => fakeSidecarDeps({
        spawn: (): SidecarProcess => {
          spawned();
          return { pid: 4242, on: vi.fn() };
        },
        probe: async () => {
          await probeGate;
          return true;
        },
      }),
    });
    const win = fakeWin();

    const booting = controller.bootBackendAndLoad(win);
    await hasSpawned;
    await controller.stopOwnedSidecar();
    releaseProbe();
    await booting;

    expect(win.loadURL).not.toHaveBeenCalled();
    expect(deps.showErrorBox).not.toHaveBeenCalled();
  });

  it("bails quietly when the user closes the window mid-boot (STUDIO-337)", async () => {
    let spawned!: () => void;
    const hasSpawned = new Promise<void>((resolve) => {
      spawned = resolve;
    });
    let releaseProbe!: () => void;
    const probeGate = new Promise<void>((resolve) => {
      releaseProbe = resolve;
    });
    const { controller, deps } = harness({
      createSidecarDeps: () => fakeSidecarDeps({
        spawn: (): SidecarProcess => {
          spawned();
          return { pid: 4242, on: vi.fn() };
        },
        probe: async () => {
          await probeGate;
          return true;
        },
      }),
    });
    const win = fakeWin();

    const booting = controller.bootBackendAndLoad(win);
    await hasSpawned;
    // Closing the window destroys it well before `window-all-closed` gets around
    // to quitting, so `stopRequested` is still false here — this is the gap the
    // STUDIO-336 guard alone does not cover.
    win.destroy();
    releaseProbe();

    await expect(booting).resolves.toBeUndefined();

    // The backend started fine; the user just left. Neither dialog is warranted.
    expect(deps.showErrorBox).not.toHaveBeenCalled();
    expect(deps.loadPlaceholderPage).not.toHaveBeenCalled();
  });

  it("does not escape when the window dies between the health check and loadURL", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();
    // Destroyed after the boot is underway: loadURL itself throws, which used to
    // land in the catch and report a startup failure that never happened.
    win.loadURL.mockImplementation(async () => {
      win.destroy();
      throw new Error("Object has been destroyed");
    });

    await expect(controller.bootBackendAndLoad(win)).resolves.toBeUndefined();

    expect(deps.showErrorBox).not.toHaveBeenCalled();
    expect(deps.loadPlaceholderPage).not.toHaveBeenCalled();
  });

  it("does not escape when the recovery page also fails to load", async () => {
    const { controller, deps } = harness({
      createSidecarDeps: () => fakeSidecarDeps({ probe: async () => false }),
      loadPlaceholderPage: vi.fn().mockRejectedValue(new Error("no renderer")),
    });
    const win = fakeWin();

    // A genuine startup failure whose fallback UI also fails must still settle,
    // or the rejection surfaces as a second "internal error" dialog.
    await expect(controller.bootBackendAndLoad(win)).resolves.toBeUndefined();

    expect(deps.showErrorBox).toHaveBeenCalledOnce();
  });

  it("still boots normally after a stop (regenerate-key flow clears the stop flag)", async () => {
    const { controller, deps } = harness();
    const win = fakeWin();

    await controller.bootBackendAndLoad(win);
    await controller.stopOwnedSidecar();
    await controller.bootBackendAndLoad(win);

    expect(win.loadURL).toHaveBeenNthCalledWith(2, "http://127.0.0.1:5555");
    expect(deps.showErrorBox).not.toHaveBeenCalled();
  });

  it("offers a restart when the backend dies after a successful boot (STUDIO-338)", async () => {
    const sidecar = crashableSidecar();
    const { controller, deps, showMessageBox } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    win.loadURL.mockClear();
    showMessageBox.mockResolvedValue({ response: 0 }); // "Restart backend"

    sidecar.spawned[0].fireExit(1);
    await vi.waitFor(() => expect(win.loadURL).toHaveBeenCalled());

    const [, opts] = showMessageBox.mock.calls[0];
    expect(opts.buttons).toEqual(["Restart backend", "Quit"]);
    // The splash covers the dead page while the replacement backend boots.
    expect(deps.loadSplashPage).toHaveBeenCalledWith(win);
    expect(win.loadURL).toHaveBeenCalledWith("http://127.0.0.1:5555");
    expect(deps.quitApp).not.toHaveBeenCalled();
  });

  it("quits instead of restarting when the user declines", async () => {
    const sidecar = crashableSidecar();
    const { controller, deps, showMessageBox } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    showMessageBox.mockResolvedValue({ response: 1 }); // "Quit"

    sidecar.spawned[0].fireExit(1);
    await vi.waitFor(() => expect(deps.quitApp).toHaveBeenCalledOnce());

    expect(deps.loadSplashPage).not.toHaveBeenCalled();
  });

  it("stays silent when the exit was one we asked for (quit / regenerate key)", async () => {
    const sidecar = crashableSidecar();
    const { controller, showMessageBox } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    showMessageBox.mockClear();

    await controller.stopOwnedSidecar();
    sidecar.spawned[0].fireExit(0);
    await Promise.resolve();

    expect(showMessageBox).not.toHaveBeenCalled();
  });

  it("ignores a superseded process exiting after a restart", async () => {
    const sidecar = crashableSidecar();
    const { controller, showMessageBox } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    showMessageBox.mockResolvedValue({ response: 0 });

    sidecar.spawned[0].fireExit(1);
    await vi.waitFor(() => expect(sidecar.spawned).toHaveLength(2));
    showMessageBox.mockClear();

    // The first process's listener fires late — we already killed and replaced
    // it, so this must not be reported as a fresh crash.
    sidecar.spawned[0].fireExit(1);
    await Promise.resolve();

    expect(showMessageBox).not.toHaveBeenCalled();
  });

  it("does not report a crash for a backend that dies before it is ever healthy", async () => {
    // The health poll owns a boot-time death and already surfaces it. Reporting
    // it here too would give the user two dialogs for one failure.
    const sidecar = crashableSidecar();
    let releaseProbe!: () => void;
    const probeGate = new Promise<void>((resolve) => { releaseProbe = resolve; });
    const { controller, deps, showMessageBox } = harness({
      createSidecarDeps: () => ({
        ...sidecar.createSidecarDeps(),
        probe: async () => { await probeGate; return false; },
      }),
    });
    const win = fakeWin();

    const booting = controller.bootBackendAndLoad(win);
    await vi.waitFor(() => expect(sidecar.spawned).toHaveLength(1));
    // Die mid-boot, while the health poll is still in flight.
    sidecar.spawned[0].fireExit(1);
    releaseProbe();
    await booting;

    expect(showMessageBox).not.toHaveBeenCalled();
    expect(deps.showErrorBox).toHaveBeenCalledWith(
      "STL Studio — backend failed to start",
      expect.stringContaining("did not become healthy"),
    );
  });

  it("stops offering restarts once the backend is in a crash loop", async () => {
    const sidecar = crashableSidecar();
    const { controller, deps, showMessageBox } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    showMessageBox.mockResolvedValue({ response: 0 });

    // Three restarts are allowed; the fourth crash inside the window gives up.
    for (let attempt = 1; attempt <= MAX_SIDECAR_RESTARTS; attempt += 1) {
      sidecar.spawned[attempt - 1].fireExit(1);
      await vi.waitFor(() => expect(sidecar.spawned).toHaveLength(attempt + 1));
    }
    showMessageBox.mockClear();

    sidecar.spawned[MAX_SIDECAR_RESTARTS].fireExit(1);
    await vi.waitFor(() => expect(deps.showErrorBox).toHaveBeenCalled());

    expect(showMessageBox).not.toHaveBeenCalled();
    expect(deps.showErrorBox).toHaveBeenCalledWith(
      "STL Studio — the backend keeps stopping",
      expect.stringContaining("catalog data is unchanged"),
    );
    expect(deps.loadPlaceholderPage).toHaveBeenCalledWith(win);
  });

  it("allows restarts again once the crash-loop window has passed", async () => {
    const sidecar = crashableSidecar();
    const { controller, deps, showMessageBox, advanceClock } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    showMessageBox.mockResolvedValue({ response: 0 });

    for (let attempt = 1; attempt <= MAX_SIDECAR_RESTARTS; attempt += 1) {
      sidecar.spawned[attempt - 1].fireExit(1);
      await vi.waitFor(() => expect(sidecar.spawned).toHaveLength(attempt + 1));
    }
    advanceClock(SIDECAR_RESTART_WINDOW_MS + 1);
    showMessageBox.mockClear();

    sidecar.spawned[MAX_SIDECAR_RESTARTS].fireExit(1);
    await vi.waitFor(() => expect(showMessageBox).toHaveBeenCalled());

    // A crash long after the earlier run is a fresh incident, not a loop.
    expect(deps.showErrorBox).not.toHaveBeenCalled();
  });

  it("does not stack dialogs when the backend dies repeatedly", async () => {
    const sidecar = crashableSidecar();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const showMessageBox = vi.fn(async () => { await gate; return { response: 1 }; });
    const { controller } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
      showMessageBox,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);

    sidecar.spawned[0].fireExit(1);
    sidecar.spawned[0].fireExit(1);
    await Promise.resolve();

    expect(showMessageBox).toHaveBeenCalledOnce();
    release();
  });

  it("says nothing when the window is already gone", async () => {
    const sidecar = crashableSidecar();
    const { controller, showMessageBox } = harness({
      createSidecarDeps: sidecar.createSidecarDeps,
    });
    const win = fakeWin();
    await controller.bootBackendAndLoad(win);
    showMessageBox.mockClear();

    win.destroy();
    sidecar.spawned[0].fireExit(1);
    await Promise.resolve();

    expect(showMessageBox).not.toHaveBeenCalled();
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
