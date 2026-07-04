import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import { QueryWrapper } from "../test/queryWrapper";

// api.models.list is the call we assert against; everything else just needs to
// resolve so the page's mount effects settle.
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
    scan: { roots: vi.fn().mockResolvedValue([]) },
    files: { driveStatus: vi.fn().mockResolvedValue({ roots: [], all_available: true }) },
    painting: { guides: { modelIds: vi.fn().mockResolvedValue({ model_ids: [] }) } },
  },
}));

vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: mkSettings(),
    update: vi.fn(),
    upsertPreset: vi.fn(),
    deletePreset: vi.fn(),
  }),
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

const LIBRARY_QUERY_KEY = "library_query";

describe("Library filter stickiness (#288)", () => {
  beforeEach(() => {
    listMock.mockClear();
    sessionStorage.clear();
  });

  it("resumes the saved filter set when entered with no params", async () => {
    sessionStorage.setItem(LIBRARY_QUERY_KEY, "creator_id=5");
    renderAt("/");
    await flush();

    // The empty-URL entry is upgraded to the remembered query, so the fetch
    // carries the prior filter rather than listing everything.
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ creator_id: "5" }));
  });

  it("does not override an explicit query in the URL", async () => {
    sessionStorage.setItem(LIBRARY_QUERY_KEY, "creator_id=5");
    renderAt("/?creator_id=9");
    await flush();

    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ creator_id: "9" }));
    expect(listMock).not.toHaveBeenCalledWith(expect.objectContaining({ creator_id: "5" }));
  });

  it("persists the active filter set for the next entry", async () => {
    renderAt("/?creator_id=7");
    await flush();
    expect(sessionStorage.getItem(LIBRARY_QUERY_KEY)).toBe("creator_id=7");
  });

  it("forgets the saved query when filters are cleared (deliberate reset stays reset)", async () => {
    renderAt("/?source_site=gumroad");
    await flush();
    expect(sessionStorage.getItem(LIBRARY_QUERY_KEY)).toBe("source_site=gumroad");

    // The filters panel auto-opens when a filter is active, so Clear all is
    // already on screen.
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /clear all/i })); });
    await flush();

    expect(sessionStorage.getItem(LIBRARY_QUERY_KEY)).toBeNull();
  });
});
