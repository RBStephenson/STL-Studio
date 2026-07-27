/**
 * Library wiring for the variant group side panel (STUDIO-350).
 *
 * The panel's open state is a URL query param rather than component state, so
 * Back, deep links and reload all keep working. These tests pin that contract
 * plus the feature flag, which must leave the old navigation completely intact
 * when off.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import { QueryWrapper } from "../test/queryWrapper";

const GROUP_CARD = {
  id: 1, name: "Winged Guardian", title: "Winged Guardian", creator_id: 7,
  character: "Winged Guardian", variant_count: 6, variant_group_id: 99,
  variant_group: { label: "Winged Guardian" },
  auto_tags: [], removed_auto_tags: [], tags: [],
};
// A pre-durable-group card: multi-variant but no id to fetch by.
const LEGACY_CARD = { ...GROUP_CARD, id: 2, variant_group_id: null, variant_group: null };
const SINGLE_CARD = { ...GROUP_CARD, id: 3, variant_count: 1, variant_group_id: null, variant_group: null };

const listMock = vi.fn();
const variantsMock = vi.fn();
let settings = mkSettings({ variant_sidebar_enabled: true });

vi.mock("../api/client", () => ({
  PRINT_STATUS_LABELS: { none: "Not printed", queued: "Queued", printing: "Printing", printed: "Printed" },
  PRINT_STATUS_CYCLE: ["none", "queued", "printing", "printed"],
  api: {
    fileUrl: (p: string) => `/files/${p}`,
    models: {
      list: (...a: unknown[]) => listMock(...a),
      variants: (...a: unknown[]) => variantsMock(...a),
      creators: vi.fn().mockResolvedValue([]),
      stats: vi.fn().mockResolvedValue({}),
      tags: vi.fn().mockResolvedValue([]),
    },
    collections: { list: vi.fn().mockResolvedValue([]) },
    scan: {
      roots: vi.fn().mockResolvedValue([]),
      status: vi.fn().mockResolvedValue({ running: false, message: "" }),
      start: vi.fn(), cancel: vi.fn(),
    },
    files: { driveStatus: vi.fn().mockResolvedValue({ roots: [], all_available: true }) },
    painting: { guides: { modelIds: vi.fn().mockResolvedValue({ model_ids: [] }) } },
  },
}));

vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings, update: vi.fn() }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ScanButton", () => ({ default: () => null }));
vi.mock("../components/BulkTagBar", () => ({ default: () => null }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

/** Surfaces the router's current location so a test can assert that a click
 *  actually navigated, not merely that no panel appeared. */
function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function renderAt(entry = "/") {
  return render(
    <QueryWrapper>
      <MemoryRouter initialEntries={[entry]}>
        <Library />
        <LocationProbe />
      </MemoryRouter>
    </QueryWrapper>,
  );
}

const location = () => screen.getByTestId("loc").textContent ?? "";

const panel = () => screen.queryByRole("complementary", { name: /variants of/i });

/** A card renders several links (the card itself, plus inner affordances), so
 *  select the card anchor by its href rather than by accessible name. */
async function cardLink(hrefFragment: string) {
  return await waitFor(() => {
    const match = screen.getAllByRole("link")
      .find((a) => a.getAttribute("href")?.includes(hrefFragment));
    if (!match) throw new Error(`no card link containing ${hrefFragment}`);
    return match;
  });
}

beforeEach(() => {
  settings = mkSettings({ variant_sidebar_enabled: true });
  listMock.mockReset().mockResolvedValue({ items: [GROUP_CARD], total: 1 });
  variantsMock.mockReset().mockResolvedValue({
    items: [{ ...GROUP_CARD, id: 11, title: "Winged Guardian - Base", is_group_rep: true }],
    total: 1,
  });
  localStorage.clear();
});

describe("opening and closing", () => {
  it("opens the panel and records the group in the URL", async () => {
    renderAt();
    await userEvent.click(await cardLink("/groups/7/"));

    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(location()).toContain("group=99");
    // Still on the Library, not navigated to the group page.
    expect(location()).toMatch(/^\/\?/);
    expect(variantsMock.mock.calls[0][2]).toBe(99);
  });

  it("opens straight from a deep link, without a click", async () => {
    renderAt("/?group=99");
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(variantsMock).toHaveBeenCalled();
  });

  it("closes when the group param goes away", async () => {
    renderAt("/?group=99");
    await waitFor(() => expect(panel()).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /close variants panel/i }));
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    expect(location()).not.toContain("group=");
  });

  it("keeps other Library params when opening and closing", async () => {
    renderAt("/?page=3&creator_id=7&group=99");
    await waitFor(() => expect(panel()).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /close variants panel/i }));
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    // Closing must drop only `group`, never the caller's filters.
    expect(location()).toContain("page=3");
    expect(location()).toContain("creator_id=7");
    expect(location()).not.toContain("group=");
  });

  it("keeps existing filters when opening from a filtered view", async () => {
    // Opening must merge `group` into the current params, not replace them —
    // replacing would silently drop the user's page and filters.
    renderAt("/?page=3&creator_id=7");
    await userEvent.click(await cardLink("/groups/7/"));
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(location()).toContain("page=3");
    expect(location()).toContain("creator_id=7");
    expect(location()).toContain("group=99");
  });

  it("ignores a stale group id by rendering an empty panel, not an error", async () => {
    variantsMock.mockResolvedValue({ items: [], total: 0 });
    renderAt("/?group=99999");
    expect(await screen.findByText(/no models in it/i)).toBeInTheDocument();
  });
});

describe("which cards open the panel", () => {
  it("leaves single-model cards navigating to the model", async () => {
    listMock.mockResolvedValue({ items: [SINGLE_CARD], total: 1 });
    renderAt();
    const link = await cardLink("/models/3");
    await userEvent.click(link);
    await waitFor(() => expect(location()).toContain("/models/3"));
    expect(panel()).not.toBeInTheDocument();
  });

  it("leaves legacy groups with no durable id navigating to the full page", async () => {
    // These predate first-class variant groups, so there is no id to fetch by.
    listMock.mockResolvedValue({ items: [LEGACY_CARD], total: 1 });
    renderAt();
    await userEvent.click(await cardLink("/groups/7/"));
    await waitFor(() => expect(location()).toContain("/groups/7/"));
    expect(panel()).not.toBeInTheDocument();
    expect(variantsMock).not.toHaveBeenCalled();
  });
});

describe("feature flag", () => {
  it("changes nothing when off: cards navigate and no panel exists", async () => {
    settings = mkSettings({ variant_sidebar_enabled: false });
    renderAt();
    const link = await cardLink("/groups/7/");
    await userEvent.click(link);
    // The click must still navigate — a stray preventDefault would strand the
    // user on the Library with nothing shown.
    await waitFor(() => expect(location()).toContain("/groups/7/"));
    expect(location()).not.toContain("group=");
    expect(panel()).not.toBeInTheDocument();
    expect(variantsMock).not.toHaveBeenCalled();
  });

  it("does not open from a deep link when off", async () => {
    settings = mkSettings({ variant_sidebar_enabled: false });
    renderAt("/?group=99");
    await cardLink("/groups/7/");
    expect(panel()).not.toBeInTheDocument();
  });
});

describe("panel width persistence", () => {
  it("restores a stored width", async () => {
    localStorage.setItem("variant_panel_width", "420");
    renderAt("/?group=99");
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(panel()).toHaveStyle({ width: "420px" });
  });

  it("clamps a stored width that would starve the grid on this window", async () => {
    localStorage.setItem("variant_panel_width", "5000");
    renderAt("/?group=99");
    await waitFor(() => expect(panel()).toBeInTheDocument());
    const width = parseInt((panel() as HTMLElement).style.width, 10);
    expect(width).toBeLessThanOrEqual(Math.round(window.innerWidth * 0.45));
  });
});
