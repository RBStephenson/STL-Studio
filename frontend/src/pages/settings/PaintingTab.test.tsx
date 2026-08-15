import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PaintingTab from "./PaintingTab";
import { mkSettings } from "../../test/settings";
import { AppSettings } from "../../api/client";

let settings: AppSettings = mkSettings();
const updateMock = vi.fn().mockResolvedValue(undefined);
vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings, update: updateMock }),
}));

const renderTab = () => render(<PaintingTab />);

describe("PaintingTab swatch chart import setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
  });

  it("reflects the default-off flag as unchecked", () => {
    settings = mkSettings({ paint_swatch_import_enabled: false });
    renderTab();
    expect(screen.getByRole("checkbox", { name: /enable swatch chart import/i })).not.toBeChecked();
  });

  it("reflects an already-on setting as checked", () => {
    settings = mkSettings({ paint_swatch_import_enabled: true });
    renderTab();
    expect(screen.getByRole("checkbox", { name: /enable swatch chart import/i })).toBeChecked();
  });

  it("toggling it on persists paint_swatch_import_enabled=true", async () => {
    settings = mkSettings({ paint_swatch_import_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /enable swatch chart import/i }));
    expect(updateMock).toHaveBeenCalledWith({ paint_swatch_import_enabled: true });
  });

  it("toggling it off persists paint_swatch_import_enabled=false", async () => {
    settings = mkSettings({ paint_swatch_import_enabled: true });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /enable swatch chart import/i }));
    expect(updateMock).toHaveBeenCalledWith({ paint_swatch_import_enabled: false });
  });
});
