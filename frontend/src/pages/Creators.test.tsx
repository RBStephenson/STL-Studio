import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Creators from "./Creators";

const CREATORS = [
  { id: 1, name: "Toon Studios", source_url: null, model_count: 12 },
];

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      ...orig.api,
      models: {
        ...orig.api.models,
        creators: vi.fn(async () => CREATORS),
        deleteCreator: vi.fn(async () => undefined),
      },
      scan: {
        ...orig.api.scan,
        startCreator: vi.fn(),
        status: vi.fn(),
      },
    },
  };
});
const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("../components/RefreshEnrich", () => ({ default: () => null }));
const confirmMock = vi.fn(async () => true);
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => confirmMock }));

function renderPage() {
  return render(<MemoryRouter><Creators /></MemoryRouter>);
}

describe("Creators error state", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the shared error state on load failure, with a working Retry", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockRejectedValueOnce(new Error("Backend unreachable"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unreachable");
    expect(screen.getByText("Couldn't load creators")).toBeInTheDocument();

    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Toon Studios")).toBeInTheDocument();
  });

  it("shows the empty state when a search matches no creators", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    renderPage();

    await screen.findByText("Toon Studios");
    await userEvent.type(screen.getByPlaceholderText("Search creators…"), "nonexistent");

    expect(screen.getByText("No creators found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add creator/ })).toBeInTheDocument();
  });
});

describe("Creators delete", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("deletes the creator after confirming and removes its card", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    renderPage();
    await screen.findByText("Toon Studios");

    await userEvent.click(screen.getByRole("button", { name: /Delete Toon Studios/i }));

    expect(api.models.deleteCreator).toHaveBeenCalledWith(1);
    await screen.findByText("No creators found");
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("deleted"), "success");
  });

  it("warns that the creator's models go back to the inbox, not that they're deleted", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    renderPage();
    await screen.findByText("Toon Studios");

    await userEvent.click(screen.getByRole("button", { name: /Delete Toon Studios/i }));

    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining("sent back to the inbox") }),
    );
  });

  it("warns plainly when the creator has no models to relocate", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce([
      { id: 2, name: "Empty Studio", source_url: null, model_count: 0 },
    ]);
    renderPage();
    await screen.findByText("Empty Studio");

    await userEvent.click(screen.getByRole("button", { name: /Delete Empty Studio/i }));

    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.not.stringContaining("inbox") }),
    );
  });

  it("does nothing when the confirm dialog is declined", async () => {
    confirmMock.mockResolvedValueOnce(false);
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    renderPage();
    await screen.findByText("Toon Studios");

    await userEvent.click(screen.getByRole("button", { name: /Delete Toon Studios/i }));

    expect(api.models.deleteCreator).not.toHaveBeenCalled();
    expect(screen.getByText("Toon Studios")).toBeInTheDocument();
  });

  it("surfaces a delete failure as a toast without removing the card", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    vi.mocked(api.models.deleteCreator).mockRejectedValueOnce(new Error("Network error"));
    renderPage();
    await screen.findByText("Toon Studios");

    await userEvent.click(screen.getByRole("button", { name: /Delete Toon Studios/i }));

    await vi.waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith("Network error", "error");
    });
    expect(screen.getByText("Toon Studios")).toBeInTheDocument();
  });
});

describe("Creators rescan lifecycle", () => {
  const SCANNING = {
    running: true,
    message: "scanning",
    models_found: null,
    files_found: null,
    cancelled: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // STUDIO-349. `rescan` polls in an unbounded loop and then calls
  // loadCreators/toast/setScanningId — all state updates. Left unguarded, the
  // loop outlives navigation and keeps writing to a page that is gone. Asserted
  // on the poll count rather than a timer count, because the loop is what has
  // to stop, not any single timer.
  it("stops the rescan poll loop when the page unmounts", async () => {
    // Real time drives the clock so findBy still resolves; the 1.5s sleeps are
    // then jumped manually.
    vi.useFakeTimers({ shouldAdvanceTime: true, advanceTimeDelta: 20 });
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValue(CREATORS);
    vi.mocked(api.scan.startCreator).mockResolvedValue(SCANNING);
    vi.mocked(api.scan.status).mockResolvedValue(SCANNING);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    const { unmount } = renderPage();
    await screen.findByText("Toon Studios");
    await user.click(screen.getByTitle("Rescan Toon Studios"));

    await vi.advanceTimersByTimeAsync(4000);
    const pollsWhileMounted = vi.mocked(api.scan.status).mock.calls.length;
    expect(pollsWhileMounted).toBeGreaterThan(0);

    unmount();
    await vi.advanceTimersByTimeAsync(6000);
    expect(vi.mocked(api.scan.status).mock.calls.length).toBe(pollsWhileMounted);
  });
});
