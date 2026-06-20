import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactElement } from "react";
import { render as rtlRender, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import Settings from "./Settings";
import { AppSettingsProvider } from "../context/AppSettingsContext";
import { mkSettings } from "../test/settings";

// Settings now contains a <Link> (Library Tools → /reorganize), so every render
// needs a Router context.
const render = (ui: ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>);

vi.mock("../api/client", () => ({
  api: {
    scan: {
      roots: vi.fn().mockResolvedValue([]),
      addRoot: vi.fn().mockResolvedValue({}),
      updateRoot: vi.fn().mockResolvedValue({}),
      libraries: vi.fn().mockResolvedValue([]),
    },
    settings: {
      get: vi.fn().mockResolvedValue({
        painting_guides_enabled: false,
        show_nsfw: false,
        library_page_size: 48,
        filter_presets: [],
        recent_days: 7,
      }),
      update: vi.fn().mockResolvedValue({
        painting_guides_enabled: true,
        show_nsfw: false,
        library_page_size: 48,
        filter_presets: [],
        recent_days: 7,
      }),
      reloadEnv: vi.fn().mockResolvedValue({
        ok: true,
        scan_roots: ["/srv/a", "/srv/b"],
        drive_mappings: {},
        restart_required: ["database_url"],
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

describe("Settings – Reload .env (#140)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("POSTs the reload and flashes the result with the restart note", async () => {
    const { api } = await import("../api/client");
    render(<Settings />);

    await userEvent.click(await screen.findByRole("button", { name: /reload \.env settings/i }));

    expect(api.settings.reloadEnv).toHaveBeenCalled();
    expect(await screen.findByText(/2 scan root\(s\) from \.env/i)).toBeInTheDocument();
    expect(screen.getByText(/database_url still need a restart/i)).toBeInTheDocument();
  });

  it("surfaces the backend error when reload fails", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.reloadEnv).mockRejectedValueOnce(new Error("boom"));
    render(<Settings />);

    await userEvent.click(await screen.findByRole("button", { name: /reload \.env settings/i }));

    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});

describe("Settings – Scan ignore patterns (#31)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("adds a typed pattern, appending it to the existing list", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ scan_ignore_patterns: ["WIP"] }));
    vi.mocked(api.settings.update).mockResolvedValue(
      mkSettings({ scan_ignore_patterns: ["WIP", "_archive"] })
    );

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await screen.findByText("WIP");
    await userEvent.type(screen.getByPlaceholderText(/_archive/i), "_archive");
    // First "Add" is the ignore-pattern one (a second exists for tag rules).
    await userEvent.click(screen.getAllByRole("button", { name: /^add$/i })[0]);

    expect(api.settings.update).toHaveBeenCalledWith({
      scan_ignore_patterns: ["WIP", "_archive"],
    });
    expect(await screen.findByText("_archive")).toBeInTheDocument();
  });

  it("does not re-add a pattern that already exists", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ scan_ignore_patterns: ["WIP"] }));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await screen.findByText("WIP");
    await userEvent.type(screen.getByPlaceholderText(/_archive/i), "WIP");
    await userEvent.click(screen.getAllByRole("button", { name: /^add$/i })[0]);

    expect(api.settings.update).not.toHaveBeenCalled();
  });

  it("removes a pattern via its trash button", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(
      mkSettings({ scan_ignore_patterns: ["WIP", "_archive"] })
    );
    vi.mocked(api.settings.update).mockResolvedValue(
      mkSettings({ scan_ignore_patterns: ["_archive"] })
    );

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await userEvent.click(await screen.findByRole("button", { name: /remove WIP/i }));

    expect(api.settings.update).toHaveBeenCalledWith({ scan_ignore_patterns: ["_archive"] });
  });
});

describe("Settings – Scan tag rules (#31)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("adds a keyword→tag rule, appending to the list", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ scan_tag_rules: [] }));
    vi.mocked(api.settings.update).mockResolvedValue(
      mkSettings({ scan_tag_rules: [{ keyword: "Aztec", tag: "civ" }] })
    );

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await userEvent.type(await screen.findByPlaceholderText(/keyword/i), "Aztec");
    await userEvent.type(screen.getByPlaceholderText(/tag \(/i), "civ");
    // Two "Add" buttons on the page (ignore patterns + tag rules); the tag-rule
    // one is the second.
    await userEvent.click(screen.getAllByRole("button", { name: /^add$/i })[1]);

    expect(api.settings.update).toHaveBeenCalledWith({
      scan_tag_rules: [{ keyword: "Aztec", tag: "civ" }],
    });
  });

  it("removes a tag rule via its trash button", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(
      mkSettings({ scan_tag_rules: [{ keyword: "Aztec", tag: "civ" }] })
    );
    vi.mocked(api.settings.update).mockResolvedValue(mkSettings({ scan_tag_rules: [] }));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await userEvent.click(await screen.findByRole("button", { name: /remove Aztec to civ/i }));

    expect(api.settings.update).toHaveBeenCalledWith({ scan_tag_rules: [] });
  });
});

describe("Settings – Scan parts names (#31)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("adds a parts name, appending to the list", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ scan_parts_names: [] }));
    vi.mocked(api.settings.update).mockResolvedValue(
      mkSettings({ scan_parts_names: ["Sprues"] })
    );

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await userEvent.type(await screen.findByPlaceholderText(/Sprues/i), "Sprues");
    // Third "Add" button on the page (ignore patterns, tag rules, parts names).
    await userEvent.click(screen.getAllByRole("button", { name: /^add$/i })[2]);

    expect(api.settings.update).toHaveBeenCalledWith({ scan_parts_names: ["Sprues"] });
  });

  it("removes a parts name via its trash button", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ scan_parts_names: ["Sprues"] }));
    vi.mocked(api.settings.update).mockResolvedValue(mkSettings({ scan_parts_names: [] }));

    render(<AppSettingsProvider><Settings /></AppSettingsProvider>);

    await userEvent.click(await screen.findByRole("button", { name: /remove Sprues/i }));

    expect(api.settings.update).toHaveBeenCalledWith({ scan_parts_names: [] });
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

describe("Settings – Library name + import destination (#452)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  const root = {
    id: 7, path: "/srv/minis", enabled: true, layout: "{creator}",
    last_scanned: null, name: "minis", is_writable: false,
  };

  it("toggles is_writable via updateRoot", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.roots).mockResolvedValue([root]);

    render(<Settings />);

    const checkbox = await screen.findByRole("checkbox", { name: /import destination/i });
    await userEvent.click(checkbox);
    expect(api.scan.updateRoot).toHaveBeenCalledWith(7, { is_writable: true });
  });

  it("saves a renamed library on blur", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.roots).mockResolvedValue([root]);

    render(<Settings />);

    const input = await screen.findByDisplayValue("minis");
    await userEvent.clear(input);
    await userEvent.type(input, "terrain");
    input.blur();
    expect(api.scan.updateRoot).toHaveBeenCalledWith(7, { name: "terrain" });
  });
});
