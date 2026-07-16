/// <reference types="vite/client" />

interface Window {
  stlStudio?: {
    openLogsFolder(): Promise<string>;
    setPersistentDiagnosticsEnabled(enabled: boolean): Promise<void>;
  };
}
