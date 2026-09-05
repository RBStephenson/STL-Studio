import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LibraryTab from "./LibraryTab";
import { mkSettings } from "../../test/settings";
import { AppSettings } from "../../api/client";

let settings: AppSettings = mkSettings();
const updateMock = vi.fn().mockResolvedValue(undefined);
let settingsLoaded = true;
vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings, loaded: settingsLoaded, update: updateMock }),
}));
const scanStatusMock = vi.fn().mockResolvedValue({ running: false });
// The destination-template field is a TemplateEditor since STUDIO-402, and it
// renders a live example — so this tab now talks to the reorganize API too.
const templatePreviewMock = vi.fn();
vi.mock("../../api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    api: {
      scan: { status: () => scanStatusMock() },
      reorganize: { templatePreview: (...args: unknown[]) => templatePreviewMock(...args) },
    },
  };
});

templatePreviewMock.mockResolvedValue({
  template: "{creator}/{character}/{title}",
  samples: [{
    model_id: 1, model_name: "Joker Bust",
    source_dir: "Abe3D/Joker Bust", proposed_dir: "Abe3D/Joker/Joker Bust",
    unclassifiable: false, missing_fields: [], over_length: false, reserved_name: false,
  }],
  package_mode: false,
});

const templateField = () =>
  screen.getByRole("textbox", { name: /destination template/i });

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
    scanStatusMock.mockReturnValue(new Promise(() => {}));
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

describe("LibraryTab installer feature flag (STUDIO-389)", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
  });

  it("renders the STL Installer toggle reflecting the current flag state", () => {
    settings = mkSettings({ installer_enabled: false });
    const { unmount } = renderTab();
    expect(screen.getByRole("checkbox", { name: /enable stl installer/i })).not.toBeChecked();
    unmount();

    settings = mkSettings({ installer_enabled: true });
    renderTab();
    expect(screen.getByRole("checkbox", { name: /enable stl installer/i })).toBeChecked();
  });

  it("toggling the flag on persists installer_enabled=true", async () => {
    settings = mkSettings({ installer_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /enable stl installer/i }));
    expect(updateMock).toHaveBeenCalledWith({ installer_enabled: true });
  });
});

describe("LibraryTab hierarchy variant grouping setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
  });

  it("persists the default-off setting when enabled", async () => {
    settings = mkSettings({ hierarchy_variant_grouping_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /improve automatic variant grouping/i }));
    expect(updateMock).toHaveBeenCalledWith({ hierarchy_variant_grouping_enabled: true });
  });

  it("explains that manual decisions survive rescans", () => {
    renderTab();
    expect(screen.getByText(/manual groups and models you kept separate are never overridden/i)).toBeVisible();
  });
});

describe("LibraryTab filename slugify setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
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

describe("LibraryTab package-preserving setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
  });

  it("persists the default-off package mode when enabled", async () => {
    settings = mkSettings({ reorganize_package_mode_enabled: false });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /preserve release package structure/i }));
    expect(updateMock).toHaveBeenCalledWith({ reorganize_package_mode_enabled: true });
  });
});

describe("LibraryTab AI suggestions setting", () => {
  beforeEach(() => {
    settings = mkSettings();
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
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

describe("LibraryTab destination template builder (STUDIO-402)", () => {
  beforeEach(() => {
    settings = mkSettings({ reorganize_template: "{creator}/{character}/{title}" });
    settingsLoaded = true;
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
  });

  // The context's pre-fetch default is an empty template, so rendering the
  // editor early would flash "the template is empty" over a library that has
  // one — and offer a blur-to-save on a value the user was never shown.
  it("holds the editor back until the saved settings have loaded", () => {
    settingsLoaded = false;
    renderTab();
    expect(screen.queryByRole("textbox", { name: /destination template/i })).toBeNull();
  });

  it("seeds the builder from the saved template", () => {
    renderTab();
    expect(templateField()).toHaveValue("{creator}/{character}/{title}");
  });

  // The distinction existed in the code (Settings persists, the Reorganize page
  // is a one-off) but nothing in the UI ever said so.
  it("says this copy of the template is the saved one", () => {
    renderTab();
    expect(screen.getByText(/used by Reorganize Library/)).toHaveTextContent(
      "Saved — used by Reorganize Library, new creator folders",
    );
  });

  // STUDIO-405: the enumeration listed three of the four consumers. Import moves
  // go through the same template (`routers/imports.py` renders it on apply), and
  // a user reading a list of three has no reason to think imports are affected.
  it("names all four consumers, import moves included", () => {
    renderTab();
    expect(screen.getByText(/used by Reorganize Library/)).toHaveTextContent(
      "used by Reorganize Library, new creator folders, import moves, and the \"unorganized\" flag",
    );
  });

  // STUDIO-406: the Settings copy of the editor gets its default from the same
  // settings payload it is editing, so a non-canonical value proves the prop is
  // actually wired rather than the component falling back to a literal.
  it("offers the server's default as a preset, not a built-in one", async () => {
    settings = mkSettings({
      reorganize_template: "{creator}",
      reorganize_template_default: "{creator}/{scale}",
    });
    renderTab();
    await userEvent.click(screen.getByRole("button", { name: /Built-in default/ }));
    expect(templateField()).toHaveValue("{creator}/{scale}");
  });

  it("saves the edited template once focus leaves the builder", async () => {
    renderTab();
    const input = templateField();
    await userEvent.clear(input);
    await userEvent.type(input, "{{creator}/{{title}");
    fireEvent.blur(input, { relatedTarget: document.body });

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({ reorganize_template: "{creator}/{title}" }),
    );
  });

  // Save-on-blur plus a clickable chip is a half-typed template waiting to be
  // persisted; the editor only commits once focus leaves it entirely.
  it("does not save a half-typed template when a token chip is clicked", async () => {
    renderTab();
    const input = templateField();
    await userEvent.clear(input);
    await userEvent.type(input, "{{creator}/");
    await userEvent.click(screen.getByRole("button", { name: "{character}" }));

    expect(input).toHaveValue("{creator}/{character}");
    expect(updateMock).not.toHaveBeenCalled();
  });
});

describe("LibraryTab destination layout section (STUDIO-405)", () => {
  beforeEach(() => {
    settings = mkSettings({ reorganize_template: "{creator}/{title}" });
    settingsLoaded = true;
    vi.clearAllMocks();
    scanStatusMock.mockReturnValue(new Promise(() => {}));
  });

  // This is the whole point of the ticket. The template drives four things, only
  // one of which is Reorganize, so it belongs with the scan roots the user
  // already reads as "how my library is arranged" — not below a default-off
  // checkbox labelled Experimental, where it looked like that tool's option.
  it("puts Destination Layout ahead of Library Tools", () => {
    renderTab();
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent?.trim());
    const layout = headings.findIndex((h) => h === "Destination Layout");
    const tools = headings.findIndex((h) => h === "Library Tools");
    expect(layout).toBeGreaterThan(-1);
    expect(tools).toBeGreaterThan(-1);
    expect(layout).toBeLessThan(tools);
    // And behind the scan locations it configures, not above them.
    expect(headings.findIndex((h) => h === "Scan Locations")).toBeLessThan(layout);
  });

  // Already true before the move — the box was only ever *visually* nested
  // inside the Reorganize block, never wrapped in a conditional on the flag.
  // Pinned here because the relocation is what makes the claim legible, and a
  // future tidy-up that folds these back under the flag would be a regression.
  it("shows the template and both slugify toggles with Reorganize disabled", () => {
    settings = mkSettings({
      reorganize_enabled: false,
      reorganize_template: "{creator}/{title}",
    });
    renderTab();

    expect(templateField()).toHaveValue("{creator}/{title}");
    expect(screen.getByRole("checkbox", { name: /lowercase, hyphenated directory names/i })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /lowercase, hyphenated filenames/i })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /enable reorganize library/i })).not.toBeChecked();
  });

  // The directory-slugify toggle moved sections and had no test of its own; its
  // filename sibling did. Covering it here rather than leaving the gap open.
  it("toggling directory slugify off persists reorganize_slugify=false", async () => {
    settings = mkSettings({ reorganize_slugify: true });
    renderTab();
    await userEvent.click(screen.getByRole("checkbox", { name: /lowercase, hyphenated directory names/i }));
    expect(updateMock).toHaveBeenCalledWith({ reorganize_slugify: false });
  });

  // The two live next to each other now and both say "layout", so the section
  // has to state which direction it points or it just adds confusion.
  it("distinguishes itself from a scan root's read-direction layout", () => {
    renderTab();
    expect(
      screen.getByText(/describes how your existing folders are/i),
    ).toHaveTextContent("where models");
  });
});

describe("LibraryTab scan-running dim state", () => {
  beforeEach(() => {
    settings = mkSettings();
    settingsLoaded = true;
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
