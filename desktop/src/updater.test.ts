import { describe, expect, it, vi } from "vitest";

import { createUpdateController, readAutoUpdateEnabled } from "./updater";
import type { DownloadProgress, UpdateInfo, UpdaterAdapter, UpdateUi } from "./updater";

type Listener = (...args: never[]) => void;

function harness(enabled = true, supported = true) {
  const listeners = new Map<string, Listener>();
  const updater: UpdaterAdapter = {
    autoDownload: true,
    autoInstallOnAppQuit: true,
    allowPrerelease: true,
    on(event: string, listener: Listener) { listeners.set(event, listener); return this; },
    checkForUpdates: vi.fn().mockResolvedValue(undefined),
    downloadUpdate: vi.fn().mockResolvedValue(undefined),
    quitAndInstall: vi.fn(),
  } as UpdaterAdapter;
  const ui: UpdateUi = {
    confirmDownload: vi.fn().mockResolvedValue(true),
    showCurrent: vi.fn().mockResolvedValue(undefined),
    showError: vi.fn(),
    showProgress: vi.fn(),
    confirmRestart: vi.fn().mockResolvedValue(true),
  };
  const stopApplication = vi.fn().mockResolvedValue(undefined);
  const controller = createUpdateController({
    updater, ui, currentVersion: "1.0.0", enabled, supported,
    stopApplication, log: vi.fn(),
  });
  const emit = (event: string, value?: UpdateInfo | DownloadProgress | Error) =>
    listeners.get(event)?.(value as never);
  return { controller, updater, ui, stopApplication, emit };
}

describe("createUpdateController", () => {
  it("skips automatic checks when the persisted flag is off", async () => {
    const { controller, updater } = harness(false);
    await controller.check();
    expect(updater.checkForUpdates).not.toHaveBeenCalled();
  });

  it("lets a manual check run even when automatic checks are off", async () => {
    const { controller, updater } = harness(false);
    await controller.check(true);
    expect(updater.checkForUpdates).toHaveBeenCalledOnce();
  });

  it("downloads only after confirmation and reports bounded progress", async () => {
    const { updater, ui, emit } = harness();
    emit("update-available", { version: "1.1.0" });
    await vi.waitFor(() => expect(updater.downloadUpdate).toHaveBeenCalledOnce());
    emit("download-progress", { percent: 104 });
    expect(ui.showProgress).toHaveBeenCalledWith(100);
  });

  it("stops the sidecar before installing the downloaded update", async () => {
    const { updater, stopApplication, emit } = harness();
    emit("update-downloaded", { version: "1.1.0" });
    await vi.waitFor(() => expect(updater.quitAndInstall).toHaveBeenCalledOnce());
    expect(stopApplication.mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(updater.quitAndInstall).mock.invocationCallOrder[0],
    );
  });

  it("does not install when sidecar shutdown fails", async () => {
    const { updater, ui, stopApplication, emit } = harness();
    stopApplication.mockRejectedValueOnce(new Error("sidecar busy"));
    emit("update-downloaded", { version: "1.1.0" });
    await vi.waitFor(() => expect(ui.showError).toHaveBeenCalledWith(expect.stringMatching(/sidecar busy/i)));
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
  });

  it("does not contact the updater in unsupported builds", async () => {
    const { controller, updater, ui } = harness(true, false);
    await controller.check(true);
    expect(updater.checkForUpdates).not.toHaveBeenCalled();
    expect(ui.showError).toHaveBeenCalledWith(expect.stringMatching(/installed Windows app/i));
  });
});

describe("readAutoUpdateEnabled", () => {
  it("accepts only an explicit true from backend settings", async () => {
    await expect(readAutoUpdateEnabled("http://127.0.0.1:1", async () => ({ auto_update_enabled: true }))).resolves.toBe(true);
    await expect(readAutoUpdateEnabled("http://127.0.0.1:1", async () => ({}))).resolves.toBe(false);
  });
});
