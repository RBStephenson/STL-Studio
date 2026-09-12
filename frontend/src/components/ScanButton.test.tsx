import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, screen } from "@testing-library/react";
import ScanButton from "./ScanButton";

// api.scan.status is driven per-test; start/cancel just need to resolve.
const statusMock = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    scan: {
      status: (...a: unknown[]) => statusMock(...a),
      start: vi.fn(),
      cancel: vi.fn(),
    },
  },
}));

const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({
  useToast: () => ({ toast: toastMock }),
}));

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("ScanButton completion notification (#283)", () => {
  beforeEach(() => {
    statusMock.mockReset();
    toastMock.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("toasts the backend completion summary on running → idle", async () => {
    // Initial fetch: a scan is running. Next poll: finished with a summary.
    statusMock
      .mockResolvedValueOnce({ running: true, message: "scanning…" })
      .mockResolvedValue({ running: false, message: "done — 12 models, 34 files" });

    render(<ScanButton />);
    await flush();              // initial status() resolves → running, interval starts
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); }); // one poll → idle
    await flush();

    expect(toastMock).toHaveBeenCalledWith("done — 12 models, 34 files", "success");
  });

  it("shows the live models count without a files count while scanning (#380)", async () => {
    statusMock.mockResolvedValue({
      running: true, message: "scanning…", models_found: 7, files_found: 0,
    });

    render(<ScanButton />);
    await flush();

    expect(screen.getByText(/Scanning… 7 models/)).toBeInTheDocument();
    expect(screen.queryByText(/files/)).not.toBeInTheDocument();
  });

  it("does not toast when no scan was running (initial idle load)", async () => {
    statusMock.mockResolvedValue({ running: false, message: "" });

    render(<ScanButton />);
    await flush();

    expect(toastMock).not.toHaveBeenCalled();
  });
});

describe("ScanButton while the write lock outlives the scan job (STUDIO-450)", () => {
  beforeEach(() => {
    statusMock.mockReset();
    toastMock.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("says Finishing up and refuses the click while a cancelled scan unwinds", async () => {
    // The reported bug: the job has reached its terminal state, so `running` is
    // false — but the worker still holds the write lock, so every write 409s.
    // An enabled "Scan Library" here is the screen contradicting the API.
    statusMock.mockResolvedValue({
      running: false, busy: true, cancelled: true, message: "cancelled",
    });

    render(<ScanButton />);
    await flush();

    expect(screen.getByText(/Finishing up…/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Scan Library/ })).toBeDisabled();
  });

  it("says Library busy for a lock holder that is not a cancelled scan", async () => {
    // A reorganize apply/undo or an install. "Finishing up" would misdescribe it
    // — nothing of the user's is finishing, something else is holding the library.
    statusMock.mockResolvedValue({
      running: false, busy: true, cancelled: false, message: "idle",
    });

    render(<ScanButton />);
    await flush();

    expect(screen.getByText(/Library busy…/)).toBeInTheDocument();
    expect(screen.queryByText(/Finishing up…/)).toBeNull();
    expect(screen.getByRole("button", { name: /Scan Library/ })).toBeDisabled();
  });

  it("holds the completion toast until busy clears, not when running clears", async () => {
    statusMock
      .mockResolvedValueOnce({ running: true, busy: true, message: "scanning…" })
      .mockResolvedValueOnce({
        running: false, busy: true, cancelled: true, message: "cancelled",
      })
      .mockResolvedValue({
        running: false, busy: false, cancelled: true, message: "cancelled",
      });

    render(<ScanButton />);
    await flush();

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await flush();
    expect(toastMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Finishing up…/)).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await flush();
    expect(toastMock).toHaveBeenCalledWith("cancelled", "success");
    expect(screen.queryByText(/Finishing up…/)).toBeNull();
    expect(screen.getByRole("button", { name: /Scan Library/ })).not.toBeDisabled();
  });

  it("leaves the button enabled when the library is genuinely idle", async () => {
    statusMock.mockResolvedValue({ running: false, busy: false, message: "idle" });

    render(<ScanButton />);
    await flush();

    expect(screen.queryByText(/Finishing up…/)).toBeNull();
    expect(screen.getByRole("button", { name: /Scan Library/ })).not.toBeDisabled();
  });
});
