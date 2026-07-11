/**
 * Tests for Library group_variants param rules (#224).
 *
 * group_variants rules: the Library sets group_variants=true for the default
 * (all models) view, and false when filtering to favorites, a print_status, or
 * excluded models — those views show every variant individually.
 *
 * Saved filter presets (this file's former "preset save"/"preset apply"
 * suites) were dropped from the UI in STUDIO-128's sidebar redesign — the
 * new Sidebar no longer renders a presets panel.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import { QueryWrapper } from "../test/queryWrapper";

const listMock = vi.fn().mockResolvedValue({ items: [], total: 0 });

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
  useAppSettings: () => ({ settings: mkSettings(), update: vi.fn() }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ScanButton", () => ({ default: () => null }));
vi.mock("../components/BulkTagBar", () => ({ default: () => null }));
vi.mock("../components/ModelCard", () => ({ default: () => null }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

const renderAt = (entry: string) =>
  render(
    <QueryWrapper>
    <MemoryRouter initialEntries={[entry]}>
      <Library />
    </MemoryRouter>
    </QueryWrapper>,
  );

const flush = () => act(async () => { await Promise.resolve(); });

describe("Library group_variants param rules (#224)", () => {
  beforeEach(() => {
    listMock.mockClear();
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
