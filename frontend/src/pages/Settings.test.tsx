import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Settings from "./Settings";
import { AppSettingsProvider } from "../context/AppSettingsContext";
import { mkSettings } from "../test/settings";

vi.mock("../api/client", () => ({
  api: {
    scan: {
      roots: vi.fn().mockResolvedValue([]),
      addRoot: vi.fn().mockResolvedValue({}),
    },
    settings: {
      get: vi.fn().mockResolvedValue({
        painting_guides_enabled: false,
        show_nsfw: false,
        library_page_size: 48,
        filter_presets: [],
      }),
      update: vi.fn().mockResolvedValue({
        painting_guides_enabled: true,
        show_nsfw: false,
        library_page_size: 48,
        filter_presets: [],
      }),
    },
  },
}));

vi.mock("../components/FolderPicker", () => ({
  default: ({ onSelect, onClose }: { onSelect: (p: string) => void; onClose: () => void }) => (
    <div data-testid="folder-picker">
      <button onClick={() => onSelect("/picked/path")}>Select folder</button>
      <button onClick={onClose}>Close picker</button>
    </div>
  ),
}));

vi.mock("../components/HelpLink", () => ({ default: () => null }));

describe("Settings – Add Folder button", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("opens FolderPicker when clicked with an empty path field", async () => {
    render(<Settings />);
    expect(screen.queryByTestId("folder-picker")).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(screen.getByTestId("folder-picker")).toBeInTheDocument();
  });

  it("calls api.scan.addRoot directly when path field already has a value", async () => {
    const { api } = await import("../api/client");
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/my/models");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(api.scan.addRoot).toHaveBeenCalledWith("/my/models", "{creator}");
    expect(screen.queryByTestId("folder-picker")).toBeNull();
  });

  it("adds the folder selected via FolderPicker and closes the picker", async () => {
    const { api } = await import("../api/client");
    render(<Settings />);

    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));
    await userEvent.click(screen.getByRole("button", { name: /select folder/i }));

    expect(api.scan.addRoot).toHaveBeenCalledWith("/picked/path", "{creator}");
    expect(screen.queryByTestId("folder-picker")).toBeNull();
  });
});

describe("Settings – backend error details surfaced (#216)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the backend detail when adding a duplicate root", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.addRoot).mockRejectedValueOnce(new Error("Root already exists"));
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/dup/path");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(await screen.findByText("Root already exists")).toBeInTheDocument();
  });

  it("shows the backend's layout validation message", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.addRoot).mockRejectedValueOnce(
      new Error("Layout must contain the {creator} placeholder")
    );
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/new/path");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(
      await screen.findByText("Layout must contain the {creator} placeholder")
    ).toBeInTheDocument();
  });

  it("falls back to a generic message when the error has no detail", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.addRoot).mockRejectedValueOnce(new Error(""));
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/new/path");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(await screen.findByText("Could not add drive")).toBeInTheDocument();
  });
});

describe("Settings – Painting Guides toggle (#180)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders unchecked by default and persists enabling via the API", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: false }));
    vi.mocked(api.settings.update).mockResolvedValue(mkSettings({ painting_guides_enabled: true }));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    const checkbox = await screen.findByRole("checkbox", { name: /enable painting guides/i });
    expect(checkbox).not.toBeChecked();

    await userEvent.click(checkbox);

    expect(api.settings.update).toHaveBeenCalledWith({ painting_guides_enabled: true });
    expect(await screen.findByText("Painting Guides enabled")).toBeInTheDocument();
    expect(checkbox).toBeChecked();
  });

  it("reflects an already-enabled server setting and can disable it", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: true }));
    vi.mocked(api.settings.update).mockResolvedValue(mkSettings({ painting_guides_enabled: false }));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    const checkbox = await screen.findByRole("checkbox", { name: /enable painting guides/i });
    await screen.findByRole("checkbox", { name: /enable painting guides/i, checked: true });

    await userEvent.click(checkbox);

    expect(api.settings.update).toHaveBeenCalledWith({ painting_guides_enabled: false });
    expect(await screen.findByText("Painting Guides disabled")).toBeInTheDocument();
  });

  it("surfaces the backend error and stays unchecked when the update fails", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: false }));
    vi.mocked(api.settings.update).mockRejectedValueOnce(new Error("DB locked"));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    const checkbox = await screen.findByRole("checkbox", { name: /enable painting guides/i });
    await userEvent.click(checkbox);

    expect(await screen.findByText("DB locked")).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
  });
});

describe("Settings – Library page size (#32)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("highlights the server value and PATCHes a new size", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ library_page_size: 48 }));
    vi.mocked(api.settings.update).mockResolvedValue(mkSettings({ library_page_size: 96 }));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "96" }));

    expect(api.settings.update).toHaveBeenCalledWith({ library_page_size: 96 });
  });
});
