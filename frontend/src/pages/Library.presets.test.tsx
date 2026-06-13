/**
 * Tests for Library preset save/apply and group_variants param rules (#224).
 *
 * group_variants rules: the Library sets group_variants=true for the default
 * (all models) view, and false when filtering to favorites, a print_status, or
 * excluded models — those views show every variant individually.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import type { AppSettings } from "../api/client";

const listMock = vi.fn().mockResolvedValue({ items: [], total: 0 });
const upsertPresetMock = vi.fn();
const deletePresetMock = vi.fn();

// settingsOverride lets individual tests inject presets without re-mocking.
let settingsOverride: Partial<AppSettings> = {};

vi.mock("../api/client", () => ({
  PRINT_STATUS_LABELS: { none: "Not printed", queued: "Queued", printing: "Printing", printed: "Printed" },
  PRINT_STATUS_CYCLE: ["none", "queued", "printing", "printed"],
  api: {
    models: {
      list: (...args: unknown[]) => listMock(...args),
      creators: vi.fn().mockResolvedValue([]),
      stats: vi.fn().mockResolvedValue({}),
      tags: vi.fn().mockResolvedValue([]),
    },
    collections: { list: vi.fn().mockResolvedValue([]) },
    scan: { roots: vi.fn().mockResolvedValue([]) },
    painting: { guides: { modelIds: vi.fn().mockResolvedValue({ model_ids: [] }) } },
  },
}));

vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: mkSettings(settingsOverride),
    update: vi.fn(),
    upsertPreset: upsertPresetMock,
    deletePreset: deletePresetMock,
  }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ScanButton", () => ({ default: () => null }));
vi.mock("../components/BulkTagBar", () => ({ default: () => null }));
vi.mock("../components/ModelCard", () => ({ default: () => null }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

const renderAt = (entry: string) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Library />
    </MemoryRouter>,
  );

const flush = () => act(async () => { await Promise.resolve(); });

async function openFilters() {
  const btn = screen.getByRole("button", { name: /filters/i });
  await act(async () => { fireEvent.click(btn); });
}

// ---------------------------------------------------------------------------
// group_variants rules
// ---------------------------------------------------------------------------
describe("Library group_variants param rules (#224)", () => {
  beforeEach(() => {
    listMock.mockClear();
    settingsOverride = {};
    sessionStorage.clear();
  });

  it("sends group_variants=true for the default unfiltered view", async () => {
    renderAt("/");
    await flush();
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ group_variants: true }));
  });

  it("sends group_variants=false when filtering to favorites", async () => {
    renderAt("/?is_favorite=1");
    await flush();
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ group_variants: false }));
  });

  it("sends group_variants=false when filtering by print_status", async () => {
    renderAt("/?print_status=printed");
    await flush();
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ group_variants: false }));
  });

  it("sends group_variants=false when viewing excluded models", async () => {
    renderAt("/?excluded=1");
    await flush();
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ group_variants: false }));
  });
});

// ---------------------------------------------------------------------------
// Preset save
// ---------------------------------------------------------------------------
describe("Library preset save (#224)", () => {
  beforeEach(() => {
    listMock.mockClear();
    upsertPresetMock.mockClear();
    settingsOverride = {};
    sessionStorage.clear();
  });

  it("does not show Save preset button when no filters are active", async () => {
    renderAt("/");
    await flush();
    await openFilters();
    expect(screen.queryByText("Save preset")).not.toBeInTheDocument();
  });

  it("calls upsertPreset with name and current querystring", async () => {
    renderAt("/?source_site=gumroad");
    await flush();
    // Filters panel auto-opens when hasFilters is true — no need to click Filters.

    await act(async () => { fireEvent.click(screen.getByText("Save preset")); });

    const input = screen.getByPlaceholderText("Preset name…") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Gumroad only" } });
    await act(async () => { fireEvent.click(screen.getByText("Save")); });

    expect(upsertPresetMock).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Gumroad only", qs: "source_site=gumroad" }),
    );
  });

  it("does not call upsertPreset when name is blank", async () => {
    renderAt("/?source_site=gumroad");
    await flush();

    await act(async () => { fireEvent.click(screen.getByText("Save preset")); });
    await act(async () => { fireEvent.click(screen.getByText("Save")); });

    expect(upsertPresetMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Preset apply
// ---------------------------------------------------------------------------
describe("Library preset apply (#224)", () => {
  beforeEach(() => {
    listMock.mockClear();
    settingsOverride = {};
    sessionStorage.clear();
  });

  it("clicking a preset pill re-fetches with that preset's params", async () => {
    settingsOverride = { filter_presets: [{ name: "Gumroad", qs: "source_site=gumroad" }] };
    // Start with no filters — preset pills still show when presets exist.
    // Filters panel auto-opens only when hasFilters is true; open it manually here.
    renderAt("/");
    await flush();
    await openFilters();
    listMock.mockClear();

    await act(async () => { fireEvent.click(screen.getByText("Gumroad")); });
    await flush();

    expect(listMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ source_site: "gumroad", group_variants: true }),
    );
  });

  it("preset pill does not include page param in applied filter", async () => {
    // Presets are saved without page; applying one should not send page=1 in the
    // filter (Library resets to page 1 automatically via URL, but the preset qs
    // itself should not carry it).
    settingsOverride = { filter_presets: [{ name: "Favs", qs: "is_favorite=1" }] };
    renderAt("/?page=3");
    await flush();
    // page=3 alone doesn't set hasFilters, so manually open the panel.
    await openFilters();
    listMock.mockClear();

    await act(async () => { fireEvent.click(screen.getByText("Favs")); });
    await flush();

    expect(listMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_favorite: true, group_variants: false }),
    );
  });
});
