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
