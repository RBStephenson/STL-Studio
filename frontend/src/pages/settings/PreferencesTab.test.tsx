import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PreferencesTab from "./PreferencesTab";
import { mkSettings } from "../../test/settings";

const updateMock = vi.fn().mockResolvedValue(undefined);
let enabled = false;
let recoveryEnabled = false;
let autoUpdateEnabled = true;
let persistentDiagnosticsEnabled = false;

vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: mkSettings({
      system_info_enabled: enabled,
      storage_recovery_enabled: recoveryEnabled,
      auto_update_enabled: autoUpdateEnabled,
      persistent_diagnostics_enabled: persistentDiagnosticsEnabled,
    }),
    update: updateMock,
  }),
}));

describe("PreferencesTab system info setting", () => {
  beforeEach(() => {
    enabled = false;
    recoveryEnabled = false;
    autoUpdateEnabled = true;
    persistentDiagnosticsEnabled = false;
    vi.clearAllMocks();
  });

  it("persists the default-on automatic update flag when disabled", async () => {
    render(<PreferencesTab />);
    await userEvent.click(screen.getByRole("checkbox", { name: /check for desktop updates automatically/i }));
    expect(updateMock).toHaveBeenCalledWith({ auto_update_enabled: false });
  });

  it("persists the pre-release opt-in when enabled", async () => {
    render(<PreferencesTab />);
    await userEvent.click(screen.getByRole("checkbox", { name: /include pre-release/i }));
    expect(updateMock).toHaveBeenCalledWith({ allow_prerelease_updates: true });
  });

  it("hides the pre-release opt-in when automatic updates are off", () => {
    autoUpdateEnabled = false;
    render(<PreferencesTab />);
    expect(screen.queryByRole("checkbox", { name: /include pre-release/i })).toBeNull();
  });

  it("persists the default-off storage recovery flag when enabled", async () => {
    render(<PreferencesTab />);
    await userEvent.click(screen.getByRole("checkbox", { name: /external storage recovery/i }));
    expect(updateMock).toHaveBeenCalledWith({ storage_recovery_enabled: true });
  });

  it("persists the default-off flag when enabled", async () => {
    render(<PreferencesTab />);
    await userEvent.click(screen.getByRole("checkbox", { name: /show about & system info/i }));
    expect(updateMock).toHaveBeenCalledWith({ system_info_enabled: true });
  });

  it("enables persistent support logs and notifies Electron when available", async () => {
    const setEnabled = vi.fn().mockResolvedValue(undefined);
    window.stlStudio = { openLogsFolder: vi.fn(), setPersistentDiagnosticsEnabled: setEnabled };
    render(<PreferencesTab />);
    await userEvent.click(screen.getByRole("checkbox", { name: /persistent support logs/i }));
    expect(updateMock).toHaveBeenCalledWith({ persistent_diagnostics_enabled: true });
    expect(setEnabled).toHaveBeenCalledWith(true);
    delete window.stlStudio;
  });

  it("states which sensitive details are excluded", () => {
    render(<PreferencesTab />);
    expect(screen.getByText(/never includes library paths, hostnames, database locations/i)).toBeVisible();
  });
});
