import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LibraryTab from "./LibraryTab";
import { mkSettings } from "../../test/settings";
import { AppSettings } from "../../api/client";

let settings: AppSettings = mkSettings();
const updateMock = vi.fn();
vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings, update: updateMock }),
}));
vi.mock("../../api/client", () => ({ api: {} }));

const renderTab = () =>
  render(
    <MemoryRouter>
      <LibraryTab roots={[]} loading={false} onRootsChanged={() => {}} />
    </MemoryRouter>,
  );

describe("LibraryTab reorganize feature flag", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
  });

  it("hides the Reorganize Library link when the flag is off", () => {
    settings = mkSettings({ reorganize_enabled: false });
    renderTab();
    expect(screen.queryByRole("link", { name: /reorganize library/i })).toBeNull();
  });

  it("shows the Reorganize Library link when the flag is on", () => {
    settings = mkSettings({ reorganize_enabled: true });
    renderTab();
    expect(screen.getByRole("link", { name: /reorganize library/i })).toBeInTheDocument();
  });

  it("toggling the flag on persists reorganize_enabled=true", async () => {
    settings = mkSettings({ reorganize_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /enable reorganize library/i }));
    expect(updateMock).toHaveBeenCalledWith({ reorganize_enabled: true });
  });
});
