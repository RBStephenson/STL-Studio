import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("stlStudio", {
  openLogsFolder: (): Promise<string> => ipcRenderer.invoke("diagnostics:open-logs"),
  setPersistentDiagnosticsEnabled: (enabled: boolean): Promise<void> =>
    ipcRenderer.invoke("diagnostics:set-enabled", enabled),
});
