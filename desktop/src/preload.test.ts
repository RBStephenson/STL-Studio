import { describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
const exposeInMainWorld = vi.fn();

vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld },
  ipcRenderer: { invoke },
}));

describe("preload", () => {
  it("exposes stlStudio on the main world with the diagnostics bridge", async () => {
    await import("./preload");

    expect(exposeInMainWorld).toHaveBeenCalledWith(
      "stlStudio",
      expect.objectContaining({
        openLogsFolder: expect.any(Function),
        setPersistentDiagnosticsEnabled: expect.any(Function),
      }),
    );
  });

  it("openLogsFolder invokes diagnostics:open-logs", async () => {
    const { contextBridge } = await import("electron");
    const api = (contextBridge.exposeInMainWorld as ReturnType<typeof vi.fn>).mock.calls[0][1] as {
      openLogsFolder: () => Promise<string>;
      setPersistentDiagnosticsEnabled: (enabled: boolean) => Promise<void>;
    };

    invoke.mockResolvedValueOnce("/logs");
    await expect(api.openLogsFolder()).resolves.toBe("/logs");
    expect(invoke).toHaveBeenCalledWith("diagnostics:open-logs");
  });

  it("setPersistentDiagnosticsEnabled invokes diagnostics:set-enabled with the flag", async () => {
    const { contextBridge } = await import("electron");
    const api = (contextBridge.exposeInMainWorld as ReturnType<typeof vi.fn>).mock.calls[0][1] as {
      setPersistentDiagnosticsEnabled: (enabled: boolean) => Promise<void>;
    };

    invoke.mockResolvedValueOnce(undefined);
    await api.setPersistentDiagnosticsEnabled(true);
    expect(invoke).toHaveBeenCalledWith("diagnostics:set-enabled", true);
  });
});
