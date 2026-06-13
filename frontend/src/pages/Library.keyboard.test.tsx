import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import Library from "./Library";
import { mkSettings } from "../test/settings";

const listMock = vi.fn().mockResolvedValue({
  items: [
    { id: 1, name: "Alpha" },
    { id: 2, name: "Bravo" },
    { id: 3, name: "Charlie" },
  ],
  total: 3,
});

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
  useAppSettings: () => ({ settings: mkSettings(), update: vi.fn() }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ScanButton", () => ({ default: () => null }));
vi.mock("../components/BulkTagBar", () => ({ default: () => null }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

// Lightweight stand-in that surfaces the focus state the hook drives.
vi.mock("../components/ModelCard", () => ({
  default: ({ model, focused }: { model: { id: number; name: string }; focused?: boolean }) => (
    <div data-testid={`card-${model.id}`} data-focused={focused ? "1" : "0"}>
      {model.name}
    </div>
  ),
}));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname}</div>;
}

const renderLibrary = () =>
  render(
    <MemoryRouter initialEntries={["/library"]}>
      <Routes>
        <Route path="/library" element={<><Library /><LocationProbe /></>} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );

const flush = () => act(async () => { await Promise.resolve(); });
const press = (key: string) => act(() => { fireEvent.keyDown(window, { key }); });

describe("Library keyboard navigation (#169)", () => {
  beforeEach(() => listMock.mockClear());

  it("'/' focuses the search input", async () => {
    renderLibrary();
    await flush();
    const input = screen.getByPlaceholderText(/search models/i);
    expect(document.activeElement).not.toBe(input);
    press("/");
    expect(document.activeElement).toBe(input);
  });

  it("'d' moves the focus ring across cards and Enter opens the focused model", async () => {
    renderLibrary();
    await flush();

    // No card focused initially.
    expect(screen.getByTestId("card-1").dataset.focused).toBe("0");

    press("d");           // first move → first card
    expect(screen.getByTestId("card-1").dataset.focused).toBe("1");

    press("d");           // → second card
    expect(screen.getByTestId("card-1").dataset.focused).toBe("0");
    expect(screen.getByTestId("card-2").dataset.focused).toBe("1");

    press("Enter");       // open the focused model
    expect(screen.getByTestId("loc").textContent).toBe("/models/2");
  });

  it("does not steal keys while typing in the search box", async () => {
    renderLibrary();
    await flush();
    const input = screen.getByPlaceholderText(/search models/i) as HTMLInputElement;
    input.focus();
    fireEvent.keyDown(input, { key: "d" });
    // No card gained focus — the keystroke belongs to the input.
    expect(screen.getByTestId("card-1").dataset.focused).toBe("0");
  });
});
