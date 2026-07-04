import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
  useAppSettings: () => ({ settings: mkSettings(), update: vi.fn() }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ScanButton", () => ({ default: () => null }));
vi.mock("../components/BulkTagBar", () => ({ default: () => null }));
vi.mock("../components/ModelCard", () => ({ default: () => null }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

const renderLibrary = () =>
  render(
    <QueryWrapper>
    <MemoryRouter initialEntries={["/library"]}>
      <Library />
    </MemoryRouter>
    </QueryWrapper>,
  );

const flush = () => act(async () => { await Promise.resolve(); });

describe("Library search debounce (#220)", () => {
  beforeEach(() => {
    listMock.mockClear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("shows typed input immediately but only fetches the final value after the debounce", async () => {
    renderLibrary();
    await flush(); // settle mount effects (which include the initial, q-less fetch)
    listMock.mockClear();

    const input = screen.getByPlaceholderText(/search models/i) as HTMLInputElement;

    // Three keystrokes in quick succession.
    act(() => {
      fireEvent.change(input, { target: { value: "a" } });
      fireEvent.change(input, { target: { value: "ab" } });
      fireEvent.change(input, { target: { value: "abc" } });
    });

    // Local state reflects the input immediately…
    expect(input.value).toBe("abc");
    // …but nothing has been fetched yet — the debounce is still pending.
    expect(listMock).not.toHaveBeenCalled();

    // Let the debounce fire and the resulting refetch run.
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });

    // Exactly one fetch, for the final value only — intermediate keystrokes
    // were coalesced (no per-character flooding).
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(listMock).toHaveBeenCalledWith(expect.objectContaining({ q: "abc" }));
  });
});

describe("Library search clear button (#355)", () => {
  beforeEach(() => {
    listMock.mockClear();
    // The debounce test above persists its query to sessionStorage; clear it so
    // the restore-on-mount effect doesn't repopulate the search box here.
    sessionStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("is hidden until there is text, then clears the query immediately on click", async () => {
    renderLibrary();
    await flush();
    listMock.mockClear();

    const input = screen.getByPlaceholderText(/search models/i) as HTMLInputElement;

    // No text yet → no clear button.
    expect(screen.queryByLabelText(/clear search/i)).toBeNull();

    act(() => {
      fireEvent.change(input, { target: { value: "akuma" } });
    });
    expect(input.value).toBe("akuma");

    // Button now present.
    const clearBtn = screen.getByLabelText(/clear search/i);

    // Clicking clears the input without waiting for the debounce…
    act(() => {
      fireEvent.click(clearBtn);
    });
    expect(input.value).toBe("");
    // …and the button disappears again.
    expect(screen.queryByLabelText(/clear search/i)).toBeNull();

    // The cleared query is fetched (no lingering `q`), and a late debounce timer
    // from the typed value must not resurrect it.
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });
    const calls = listMock.mock.calls;
    const lastCall = calls[calls.length - 1]?.[0] ?? {};
    expect(lastCall.q ?? "").toBe("");
  });
});
