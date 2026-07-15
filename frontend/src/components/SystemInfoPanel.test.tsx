import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SystemInfoPanel, { diagnosticText } from "./SystemInfoPanel";
import { mkSettings } from "../test/settings";
import type { SystemInfo } from "../api/client";

const systemInfoMock = vi.fn();
let enabled = true;

vi.mock("../api/client", () => ({
  api: { settings: { systemInfo: (...args: unknown[]) => systemInfoMock(...args) } },
}));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: mkSettings({ system_info_enabled: enabled }) }),
}));

const healthy: SystemInfo = {
  version: "1.0.0",
  deployment_mode: "web",
  backend_status: "healthy",
  database_status: "healthy",
  libraries_configured: 2,
  libraries_enabled: 2,
  libraries_available: 2,
  last_scan: "2026-07-15T12:00:00Z",
};

describe("SystemInfoPanel", () => {
  beforeEach(() => {
    enabled = true;
    systemInfoMock.mockReset();
    systemInfoMock.mockResolvedValue(healthy);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("is absent while the feature flag is off", () => {
    enabled = false;
    render(<SystemInfoPanel />);
    expect(screen.queryByText("System Info")).toBeNull();
    expect(systemInfoMock).not.toHaveBeenCalled();
  });

  it("shows healthy, sanitized runtime details", async () => {
    render(<SystemInfoPanel />);
    expect(await screen.findByText("Hosted web")).toBeVisible();
    expect(screen.getByText("STL Studio and all enabled libraries are available.")).toBeVisible();
    expect(screen.getByText(/2 of 2 enabled available/)).toBeVisible();
  });

  it("makes degraded availability explicit without implying data loss", async () => {
    systemInfoMock.mockResolvedValue({ ...healthy, libraries_available: 1 });
    render(<SystemInfoPanel />);
    expect(await screen.findByText(/temporarily unavailable/i)).toHaveTextContent(/catalog data is retained/i);
  });

  it("copies only the allowlisted diagnostic summary", async () => {
    render(<SystemInfoPanel />);
    await userEvent.click(await screen.findByRole("button", { name: /copy diagnostics/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(diagnosticText(healthy));
    expect(screen.getByRole("button", { name: /copied/i })).toBeVisible();
  });
});
