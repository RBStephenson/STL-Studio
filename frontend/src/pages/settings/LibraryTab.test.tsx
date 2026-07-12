import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LibraryTab from "./LibraryTab";
import { mkSettings } from "../../test/settings";
import { AppSettings } from "../../api/client";

let settings: AppSettings = mkSettings();
const updateMock = vi.fn().mockResolvedValue(undefined);
vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings, update: updateMock }),
}));
const scanStatusMock = vi.fn().mockResolvedValue({ running: false });
vi.mock("../../api/client", () => ({
  api: { scan: { status: () => scanStatusMock() } },
}));

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

  // The Reorganize Library launch point moved to the Creators toolbar's
  // "Library Tools" menu (STUDIO-155) — this tab is a pure flag now, with no
  // <Link> of its own regardless of the flag's value.
  it("never renders a Reorganize Library link, flag on or off", () => {
    settings = mkSettings({ reorganize_enabled: false });
    const { unmount } = renderTab();
    expect(screen.queryByRole("link", { name: /reorganize library/i })).toBeNull();
    unmount();

    settings = mkSettings({ reorganize_enabled: true });
    renderTab();
    expect(screen.queryByRole("link", { name: /reorganize library/i })).toBeNull();
  });

  it("toggling the flag on persists reorganize_enabled=true", async () => {
    settings = mkSettings({ reorganize_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /enable reorganize library/i }));
    expect(updateMock).toHaveBeenCalledWith({ reorganize_enabled: true });
  });
});

describe("LibraryTab filename slugify setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
  });

  it("toggling it on persists reorganize_slugify_filenames=true", async () => {
    settings = mkSettings({ reorganize_slugify_filenames: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /lowercase, hyphenated filenames/i }));
    expect(updateMock).toHaveBeenCalledWith({ reorganize_slugify_filenames: true });
  });

  it("reflects an already-on setting as checked", () => {
    settings = mkSettings({ reorganize_slugify_filenames: true });
    renderTab();
    expect(screen.getByRole("checkbox", { name: /lowercase, hyphenated filenames/i })).toBeChecked();
  });
});

describe("LibraryTab AI suggestions setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
  });

  it("toggling it on persists reorganize_ai_suggestions_enabled=true", async () => {
    settings = mkSettings({ reorganize_ai_suggestions_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /ai-assisted field suggestions/i }));
    expect(updateMock).toHaveBeenCalledWith({ reorganize_ai_suggestions_enabled: true });
  });

  it("reflects an already-on setting as checked", () => {
    settings = mkSettings({ reorganize_ai_suggestions_enabled: true });
    renderTab();
    expect(screen.getByRole("checkbox", { name: /ai-assisted field suggestions/i })).toBeChecked();
  });
});

describe("LibraryTab scan-running dim state", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
  });

  it("dims nothing while no scan is running", async () => {
    scanStatusMock.mockResolvedValue({ running: false });
    renderTab();
    expect(await screen.findByText("Add a Folder")).toBeVisible();
    expect(screen.getByText("Add a Folder").closest("div[style]")).toBeNull();
  });

  it("dims the folder list/tools while a scan is running", async () => {
    scanStatusMock.mockResolvedValue({ running: true });
    renderTab();
    const dimmed = await screen.findByText("Add a Folder");
    const wrapper = dimmed.closest("section")?.parentElement as HTMLElement;
    expect(wrapper.style.opacity).toBe("0.45");
    expect(wrapper.style.pointerEvents).toBe("none");
  });
});
