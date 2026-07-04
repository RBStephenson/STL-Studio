import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import { QueryWrapper } from "../test/queryWrapper";

const driveStatusMock = vi.fn();

vi.mock("../api/client", () => ({
  PRINT_STATUS_LABELS: { none: "Not printed", queued: "Queued", printing: "Printing", printed: "Printed" },
  PRINT_STATUS_CYCLE: ["none", "queued", "printing", "printed"],
  api: {
    models: {
      list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
      creators: vi.fn().mockResolvedValue([]),
      stats: vi.fn().mockResolvedValue({}),
      tags: vi.fn().mockResolvedValue([]),
    },
    collections: { list: vi.fn().mockResolvedValue([]) },
    scan: { roots: vi.fn().mockResolvedValue([{ id: 1 }]) },
    files: { driveStatus: (...args: unknown[]) => driveStatusMock(...args) },
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

const renderLib = () =>
  render(
    <QueryWrapper>
    <MemoryRouter initialEntries={["/"]}>
      <Library />
    </MemoryRouter>
    </QueryWrapper>,
  );

// A macrotask tick — enough for the TanStack drive-status query to resolve
// (a bare microtask flush settles before the query does).
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("Library drive-availability banner (#304)", () => {
  beforeEach(() => {
    driveStatusMock.mockReset();
    sessionStorage.clear();
  });

  it("warns when an enabled root is unavailable", async () => {
    driveStatusMock.mockResolvedValue({
      roots: [{ path: "/mnt/drive2", enabled: true, available: false }],
      all_available: false,
    });
    renderLib();

    // findBy* retries until the drive-status query resolves and the banner
    // renders — robust on slow CI where a fixed-time flush can race the query.
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/i);
    expect(screen.getByText("/mnt/drive2")).toBeInTheDocument();
  });

  it("shows no banner when all roots are available", async () => {
    driveStatusMock.mockResolvedValue({
      roots: [{ path: "/mnt/drive1", enabled: true, available: true }],
      all_available: true,
    });
    renderLib();
    await flush();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores a disabled unavailable root", async () => {
    driveStatusMock.mockResolvedValue({
      roots: [{ path: "/mnt/old", enabled: false, available: false }],
      all_available: true,
    });
    renderLib();
    await flush();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
