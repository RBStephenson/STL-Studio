import { EventEmitter } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const showErrorBox = vi.fn();
const showMessageBox = vi.fn().mockResolvedValue({ response: 0 });
const setApplicationMenu = vi.fn();
const menuPopup = vi.fn();
const buildFromTemplate = vi.fn().mockReturnValue({ popup: menuPopup });
const openPath = vi.fn().mockResolvedValue("");
const requestSingleInstanceLock = vi.fn().mockReturnValue(true);
const appOn = vi.fn();
const whenReadyCallbacks: Array<() => Promise<void>> = [];

class FakeWebContents extends EventEmitter {
  navigationHistory = {
    clear: vi.fn(),
    canGoBack: vi.fn().mockReturnValue(false),
    canGoForward: vi.fn().mockReturnValue(false),
    goBack: vi.fn(),
    goForward: vi.fn(),
  };
  reload = vi.fn();
}

class FakeBrowserWindow extends EventEmitter {
  static instances: FakeBrowserWindow[] = [];
  static focused: FakeBrowserWindow | null = null;
  static getFocusedWindow() {
    return FakeBrowserWindow.focused;
  }
  static getAllWindows() {
    return FakeBrowserWindow.instances;
  }

  webContents = new FakeWebContents();
  loadFile = vi.fn().mockResolvedValue(undefined);
  loadURL = vi.fn().mockResolvedValue(undefined);
  show = vi.fn();
  maximize = vi.fn();
  setMenu = vi.fn();
  setProgressBar = vi.fn();
  isMinimized = vi.fn().mockReturnValue(false);
  restore = vi.fn();
  focus = vi.fn();
  getNormalBounds = vi.fn().mockReturnValue({ width: 1280, height: 800 });
  isMaximized = vi.fn().mockReturnValue(false);

  constructor(public opts: Record<string, unknown>) {
    super();
    FakeBrowserWindow.instances.push(this);
    FakeBrowserWindow.focused = this;
  }
}

vi.mock("electron", () => ({
  app: {
    getPath: vi.fn().mockReturnValue("/userdata"),
    getVersion: vi.fn().mockReturnValue("1.2.3"),
    isPackaged: false,
    setPath: vi.fn(),
    requestSingleInstanceLock,
    whenReady: vi.fn().mockReturnValue({
      then: (cb: () => Promise<void>) => {
        whenReadyCallbacks.push(cb);
        return Promise.resolve();
      },
    }),
    on: appOn,
    quit: vi.fn(),
  },
  BrowserWindow: FakeBrowserWindow,
  Menu: {
    setApplicationMenu,
    buildFromTemplate,
  },
  dialog: { showErrorBox, showMessageBox },
  ipcMain: { handle: vi.fn() },
  screen: { getAllDisplays: vi.fn().mockReturnValue([]) },
  shell: { openPath },
}));

vi.mock("electron-updater", () => ({
  autoUpdater: { setFeedURL: vi.fn(), on: vi.fn().mockReturnThis(), checkForUpdates: vi.fn() },
}));

const bootBackendAndLoad = vi.fn().mockResolvedValue(undefined);
const stopOwnedSidecar = vi.fn().mockResolvedValue(undefined);
const checkForUpdatesManually = vi.fn();
const regenerateEncryptionKey = vi.fn().mockResolvedValue(undefined);
let capturedDeps: Record<string, unknown> | undefined;

vi.mock("./appController", () => ({
  createAppController: vi.fn((deps: Record<string, unknown>) => {
    capturedDeps = deps;
    return { bootBackendAndLoad, stopOwnedSidecar, checkForUpdatesManually, regenerateEncryptionKey };
  }),
}));

// Real PersistentLogger does a real mkdirSync — stub the class only, keep
// diagnosticsWereEnabled real so its env-var/marker-file logic is exercised
// as main.ts actually calls it (STUDIO-352 coverage is in
// persistentLogger.test.ts; this file only proves main.ts's wiring).
const persistentLoggerCtor = vi.fn().mockImplementation(function PersistentLoggerStub() {
  return { write: vi.fn(), flush: vi.fn().mockResolvedValue(undefined) };
});
vi.mock("./persistentLogger", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./persistentLogger")>();
  return { ...actual, PersistentLogger: persistentLoggerCtor };
});

beforeEach(() => {
  vi.clearAllMocks();
  whenReadyCallbacks.length = 0;
  FakeBrowserWindow.instances.length = 0;
  FakeBrowserWindow.focused = null;
  capturedDeps = undefined;
});

afterEach(() => {
  delete process.env.STL_STUDIO_DIAGNOSTICS;
});

async function loadMain() {
  vi.resetModules();
  await import("./main");
  // whenReady().then(cb) captured cb — run it to drive the boot sequence.
  await whenReadyCallbacks[0]?.();
}

describe("main.ts wiring", () => {
  it("acquires the single-instance lock and boots the window", async () => {
    await loadMain();
    expect(requestSingleInstanceLock).toHaveBeenCalledOnce();
    expect(FakeBrowserWindow.instances).toHaveLength(1);
    expect(bootBackendAndLoad).toHaveBeenCalledWith(FakeBrowserWindow.instances[0]);
    expect(setApplicationMenu).toHaveBeenCalled();
  });

  it("quits immediately when the single-instance lock is denied", async () => {
    requestSingleInstanceLock.mockReturnValueOnce(false);
    const { app } = await import("electron");
    await loadMain();
    expect(app.quit).toHaveBeenCalled();
    expect(FakeBrowserWindow.instances).toHaveLength(0);
  });

  it("focuses and restores the existing window on second-instance", async () => {
    await loadMain();
    const win = FakeBrowserWindow.instances[0];
    win.isMinimized.mockReturnValue(true);
    const secondInstanceHandler = appOn.mock.calls.find(([event]) => event === "second-instance")?.[1] as () => void;
    secondInstanceHandler();
    expect(win.restore).toHaveBeenCalled();
    expect(win.focus).toHaveBeenCalled();
  });

  it("creates a new window on activate when none remain", async () => {
    await loadMain();
    FakeBrowserWindow.instances.length = 0;
    const { app } = await import("electron");
    const activate = (app.on as ReturnType<typeof vi.fn>).mock.calls.find(([event]) => event === "activate")?.[1] as
      | (() => Promise<void>)
      | undefined;
    await activate?.();
    expect(FakeBrowserWindow.instances).toHaveLength(1);
    expect(bootBackendAndLoad).toHaveBeenCalledTimes(2);
  });

  it("constructs a persistent logger when STL_STUDIO_DIAGNOSTICS is set, with no marker file (STUDIO-352)", async () => {
    process.env.STL_STUDIO_DIAGNOSTICS = "1";
    await loadMain();
    expect(persistentLoggerCtor).toHaveBeenCalledWith(join("/userdata", "logs"));
  });

  it("does not construct a persistent logger when neither the env var nor a marker file is set", async () => {
    await loadMain();
    expect(persistentLoggerCtor).not.toHaveBeenCalled();
  });

  it("quits normally on window-all-closed outside macOS", async () => {
    await loadMain();
    const { app } = await import("electron");
    const handler = (app.on as ReturnType<typeof vi.fn>).mock.calls.find(
      ([event]) => event === "window-all-closed",
    )?.[1] as () => void;
    handler();
    expect(app.quit).toHaveBeenCalled();
  });

  it("before-quit stops the sidecar exactly once even if fired twice", async () => {
    await loadMain();
    const { app } = await import("electron");
    const handler = (app.on as ReturnType<typeof vi.fn>).mock.calls.find(([event]) => event === "before-quit")?.[1] as (
      e: { preventDefault: () => void },
    ) => Promise<void>;
    const event = { preventDefault: vi.fn() };
    await handler(event);
    await handler(event);
    expect(stopOwnedSidecar).toHaveBeenCalledTimes(1);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
  });

  it("before-quit still quits if stopOwnedSidecar never resolves (STUDIO-340)", async () => {
    vi.useFakeTimers();
    try {
      stopOwnedSidecar.mockReturnValueOnce(new Promise(() => {}));
      await loadMain();
      const { app } = await import("electron");
      const handler = (app.on as ReturnType<typeof vi.fn>).mock.calls.find(
        ([event]) => event === "before-quit",
      )?.[1] as (e: { preventDefault: () => void }) => Promise<void>;
      const event = { preventDefault: vi.fn() };

      const settled = handler(event);
      let done = false;
      void settled.then(() => {
        done = true;
      });

      await vi.advanceTimersByTimeAsync(9_999);
      expect(done).toBe(false);
      expect(app.quit).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(1);
      await settled;
      expect(app.quit).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("flushes the persistent logger before quitting when one exists (STUDIO-342)", async () => {
    process.env.STL_STUDIO_DIAGNOSTICS = "1";
    await loadMain();
    const { app } = await import("electron");
    const logger = persistentLoggerCtor.mock.results[0].value as { flush: ReturnType<typeof vi.fn> };
    const handler = (app.on as ReturnType<typeof vi.fn>).mock.calls.find(
      ([event]) => event === "before-quit",
    )?.[1] as (e: { preventDefault: () => void }) => Promise<void>;

    await handler({ preventDefault: vi.fn() });

    expect(logger.flush).toHaveBeenCalled();
  });

  it("wires the application menu's regenerate-key action to the focused window", async () => {
    await loadMain();
    const template = buildFromTemplate.mock.calls[0][0];
    const fileMenu = template.find((item: { label?: string }) => item.label === "File");
    const regenerateItem = fileMenu.submenu.find((item: { label?: string }) => item.label?.startsWith("Regenerate"));
    regenerateItem.click();
    expect(regenerateEncryptionKey).toHaveBeenCalledWith(FakeBrowserWindow.instances[0]);
  });

  it("wires the application menu's check-for-updates action", async () => {
    await loadMain();
    const template = buildFromTemplate.mock.calls[0][0];
    const helpMenu = template.find((item: { label?: string }) => item.label === "Help");
    const checkItem = helpMenu.submenu.find((item: { label?: string }) => item.label?.startsWith("Check"));
    checkItem.click();
    expect(checkForUpdatesManually).toHaveBeenCalled();
  });

  it("routes the window's context-menu event through buildContextMenuTemplate and popup", async () => {
    await loadMain();
    const win = FakeBrowserWindow.instances[0];
    win.webContents.emit("context-menu", {}, { isEditable: false, editFlags: { canCopy: true, canPaste: false } });
    expect(menuPopup).toHaveBeenCalledWith({ window: win });
  });

  it("routes app-command mouse buttons through handleAppCommand", async () => {
    await loadMain();
    const win = FakeBrowserWindow.instances[0];
    win.webContents.navigationHistory.canGoBack.mockReturnValue(true);
    win.emit("app-command", {}, "browser-backward");
    expect(win.webContents.navigationHistory.goBack).toHaveBeenCalled();
  });

  it("retries the backend boot on the stl-studio://retry-backend will-navigate", async () => {
    await loadMain();
    const win = FakeBrowserWindow.instances[0];
    const event = { preventDefault: vi.fn() };
    win.webContents.emit("will-navigate", event, "stl-studio://retry-backend");
    expect(event.preventDefault).toHaveBeenCalled();
    await Promise.resolve();
    await Promise.resolve();
    expect(bootBackendAndLoad).toHaveBeenCalledTimes(2);
  });

  it("ignores unrelated will-navigate URLs", async () => {
    await loadMain();
    const win = FakeBrowserWindow.instances[0];
    const event = { preventDefault: vi.fn() };
    win.webContents.emit("will-navigate", event, "https://example.com");
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("schedules a window-state save on resize/move and flushes on close", async () => {
    await loadMain();
    const win = FakeBrowserWindow.instances[0];
    win.emit("resize");
    win.emit("move");
    win.emit("close");
    // No assertion on disk I/O here (windowManager.test.ts covers the persister
    // logic in isolation) — this just proves main.ts wires the events at all.
    expect(win.getNormalBounds).toHaveBeenCalled();
  });

  it("exercises the appController deps: resolveBackendExePath, createSidecarDeps, backendBaseUrl, secret-key wrappers, showErrorBox/showMessageBox/loadPlaceholderPage/log", async () => {
    await loadMain();
    const deps = capturedDeps as {
      resolveBackendExePath: () => string;
      createSidecarDeps: () => { log: (m: string) => void };
      backendBaseUrl: (port: number) => string;
      getOrCreateSecretKey: (dir: string) => { key: string; needsReveal: boolean };
      regenerateSecretKeyFile: (dir: string) => string;
      setUpdateFeedUrl: (url: string) => void;
      fetchJson: (url: string) => Promise<unknown>;
      showErrorBox: (title: string, content: string) => void;
      showMessageBox: (win: unknown, opts: Record<string, unknown>) => Promise<{ response: number }>;
      showKeyRevealWindow: (key: string) => void;
      loadPlaceholderPage: (win: { loadFile: (p: string) => Promise<void> }) => Promise<void>;
      log: (message: string) => void;
    };

    expect(deps.resolveBackendExePath()).toContain("stl-studio");
    expect(deps.backendBaseUrl(1234)).toBe("http://127.0.0.1:1234");
    expect(deps.createSidecarDeps().log).toBeTypeOf("function");

    const tmpUserData = mkdtempSync(join(tmpdir(), "stl-studio-main-test-"));
    try {
      deps.getOrCreateSecretKey(tmpUserData);
      deps.regenerateSecretKeyFile(tmpUserData);
    } finally {
      rmSync(tmpUserData, { recursive: true, force: true });
    }
    deps.setUpdateFeedUrl("http://localhost/feed");
    deps.showErrorBox("title", "content");
    expect(showErrorBox).toHaveBeenCalledWith("title", "content");

    await deps.showMessageBox(FakeBrowserWindow.instances[0], { type: "info", buttons: [], title: "t", message: "m" });
    expect(showMessageBox).toHaveBeenCalled();

    deps.showKeyRevealWindow("a-key");
    expect(FakeBrowserWindow.instances).toHaveLength(2); // main window + key-reveal window

    const win = { loadFile: vi.fn().mockResolvedValue(undefined) };
    await deps.loadPlaceholderPage(win);
    expect(win.loadFile).toHaveBeenCalled();

    deps.log("hello");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ auto_update_enabled: true }) });
    vi.stubGlobal("fetch", fetchMock);
    await expect(deps.fetchJson("http://x/api/settings")).resolves.toEqual({ auto_update_enabled: true });
    vi.unstubAllGlobals();
  });
});
