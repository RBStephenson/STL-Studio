import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useScanStatus } from "./useScanStatus";

const statusMock = vi.fn();
const startMock = vi.fn();
const cancelMock = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    scan: {
      status: (...a: unknown[]) => statusMock(...a),
      start: (...a: unknown[]) => startMock(...a),
      cancel: (...a: unknown[]) => cancelMock(...a),
    },
  },
}));

const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({
  useToast: () => ({ toast: toastMock }),
}));

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("useScanStatus", () => {
  beforeEach(() => {
    statusMock.mockReset();
    startMock.mockReset();
    cancelMock.mockReset();
    toastMock.mockReset();
    vi.useFakeTimers();
  });
  afterEach(async () => {
    await act(async () => { await vi.runOnlyPendingTimersAsync(); });
    vi.useRealTimers();
  });

  it("reflects running status and models_found from the initial poll", async () => {
    statusMock.mockResolvedValue({ running: true, message: "scanning…", models_found: 3 });
    const { result } = renderHook(() => useScanStatus());
    await flush();
    expect(result.current.status?.running).toBe(true);
    expect(result.current.status?.models_found).toBe(3);
  });

  it("calls onScanComplete once on running → idle transition", async () => {
    statusMock
      .mockResolvedValueOnce({ running: true, message: "scanning…" })
      .mockResolvedValue({ running: false, message: "done — 2 models" });
    const onScanComplete = vi.fn();
    renderHook(() => useScanStatus(onScanComplete));
    await flush();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await flush();
    expect(onScanComplete).toHaveBeenCalledTimes(1);
    expect(toastMock).toHaveBeenCalledWith("done — 2 models", "success");
  });

  it("start() calls api.scan.start and updates status", async () => {
    statusMock.mockResolvedValue({ running: false, message: "" });
    startMock.mockResolvedValue({ running: true, message: "scanning…", models_found: 0 });
    const { result } = renderHook(() => useScanStatus());
    await flush();
    await act(async () => { await result.current.start(); });
    expect(startMock).toHaveBeenCalled();
    expect(result.current.status?.running).toBe(true);
  });
});
