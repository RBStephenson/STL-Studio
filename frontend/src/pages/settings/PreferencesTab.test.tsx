import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PreferencesTab from "./PreferencesTab";
import { mkSettings } from "../../test/settings";

const updateMock = vi.fn().mockResolvedValue(undefined);
let enabled = false;

vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: mkSettings({ system_info_enabled: enabled }),
    update: updateMock,
  }),
}));

describe("PreferencesTab system info setting", () => {
  beforeEach(() => {
    enabled = false;
    vi.clearAllMocks();
  });

  it("persists the default-off flag when enabled", async () => {
    render(<PreferencesTab />);
    await userEvent.click(screen.getByRole("checkbox", { name: /show about & system info/i }));
    expect(updateMock).toHaveBeenCalledWith({ system_info_enabled: true });
  });

  it("states which sensitive details are excluded", () => {
    render(<PreferencesTab />);
    expect(screen.getByText(/never includes library paths, hostnames, database locations/i)).toBeVisible();
  });
});
