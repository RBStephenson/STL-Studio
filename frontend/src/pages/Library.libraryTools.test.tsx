import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";
import { QueryWrapper } from "../test/queryWrapper";

const navigateMock = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const orig = await importOriginal<typeof import("react-router-dom")>();
  return { ...orig, useNavigate: () => navigateMock };
});

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
    scan: {
      roots: vi.fn().mockResolvedValue([{ id: 1 }]),
      status: vi.fn().mockResolvedValue({ running: false, message: "" }),
      start: vi.fn(), cancel: vi.fn(),
    },
    files: { driveStatus: vi.fn().mockResolvedValue({ roots: [], all_available: true }) },
    painting: { guides: { modelIds: vi.fn().mockResolvedValue({ model_ids: [] }) } },
  },
}));

let reorganizeEnabled = false;
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: mkSettings({ get reorganize_enabled() { return reorganizeEnabled; } }),
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

describe("Library Tools menu (moved from Creators — ADDENDUM §7)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockClear();
    sessionStorage.clear();
    reorganizeEnabled = false;
  });

  it("hides Reorganize Library when the flag is off, shows Rescan All Folders regardless", async () => {
    renderLib();
    await userEvent.click(screen.getByRole("button", { name: /Library Tools/i }));

    expect(screen.queryByRole("button", { name: /Reorganize Library/i })).toBeNull();
    expect(screen.getByRole("button", { name: /Rescan All Folders/i })).toBeInTheDocument();
  });

  it("shows Reorganize Library when the flag is on and navigates to /reorganize", async () => {
    reorganizeEnabled = true;
    renderLib();
    await userEvent.click(screen.getByRole("button", { name: /Library Tools/i }));
    const reorgItem = screen.getByRole("button", { name: /Reorganize Library/i });
    expect(reorgItem).toBeInTheDocument();

    await userEvent.click(reorgItem);
    expect(navigateMock).toHaveBeenCalledWith("/reorganize");
    // Menu closes after navigating.
    expect(screen.queryByRole("button", { name: /Rescan All Folders/i })).toBeNull();
  });

  it("is no longer present on the Creators screen", async () => {
    vi.resetModules();
    vi.doMock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
    vi.doMock("../components/RefreshEnrich", () => ({ default: () => null }));
    vi.doMock("../api/client", async (importOriginal) => {
      const orig = await importOriginal<typeof import("../api/client")>();
      return { ...orig, api: { ...orig.api, models: { ...orig.api.models, creators: vi.fn().mockResolvedValue([]) } } };
    });
    const CreatorsPage = (await import("./Creators")).default;
    render(<MemoryRouter><CreatorsPage /></MemoryRouter>);

    await screen.findByText("(0)");
    expect(screen.queryByRole("button", { name: /Library Tools/i })).toBeNull();
    vi.doUnmock("../context/ToastContext");
    vi.doUnmock("../components/RefreshEnrich");
    vi.doUnmock("../api/client");
  });
});
