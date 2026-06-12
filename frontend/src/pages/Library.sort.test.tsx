import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import { AppSettings } from "../api/client";

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
    painting: { guides: { modelIds: vi.fn().mockResolvedValue({ model_ids: [] }) } },
  },
}));

// Settings + update mock are mutated per-test so we can vary the persisted default.
let settings: AppSettings = mkSettings();
const updateMock = vi.fn();
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings, update: updateMock }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ScanButton", () => ({ default: () => null }));
vi.mock("../components/BulkTagBar", () => ({ default: () => null }));
vi.mock("../components/ModelCard", () => ({ default: () => null }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

const renderLibrary = (initial = "/library") =>
  render(
    <MemoryRouter initialEntries={[initial]}>
      <Library />
    </MemoryRouter>,
  );

const flush = () => act(async () => { await Promise.resolve(); });
const lastSort = () => {
  const calls = listMock.mock.calls;
  const last = calls[calls.length - 1]?.[0] as { sort?: string } | undefined;
  return last?.sort;
};

describe("Library sort control (#247)", () => {
  beforeEach(() => {
    listMock.mockClear();
    updateMock.mockClear();
    settings = mkSettings();
  });

  it("defaults to Name and omits the sort param", async () => {
    renderLibrary();
    await flush();
    const select = screen.getByLabelText(/sort models/i) as HTMLSelectElement;
    expect(select.value).toBe("name");
    expect(lastSort()).toBeUndefined();
  });

  it("changing the dropdown fetches with the new sort and persists the default", async () => {
    renderLibrary();
    await flush();
    listMock.mockClear();

    const select = screen.getByLabelText(/sort models/i) as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: "creator" } });
    });

    expect(updateMock).toHaveBeenCalledWith({ library_sort: "creator" });
    expect(lastSort()).toBe("creator");
  });

  it("applies a persisted non-name default when the URL has no sort", async () => {
    settings = mkSettings({ library_sort: "added" });
    renderLibrary();
    await flush();

    const select = screen.getByLabelText(/sort models/i) as HTMLSelectElement;
    expect(select.value).toBe("added");
    expect(lastSort()).toBe("added");
  });

  it("disables the dropdown while the Recently added filter is active", async () => {
    renderLibrary("/library?added_days=7");
    await flush();
    const select = screen.getByLabelText(/sort models/i) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(select.value).toBe("added");
    expect(lastSort()).toBe("added");
  });
});
