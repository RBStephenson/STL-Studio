import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const setPrintStatus = vi.fn(async (..._args: unknown[]) => ({ print_count: 1 }));
const toast = vi.fn();

vi.mock("../../../api/client", () => ({
  PRINT_STATUS_CYCLE: ["none", "printed", "queued"],
  api: { models: { setPrintStatus: (...a: unknown[]) => setPrintStatus(...a) } },
}));
vi.mock("../../../context/ToastContext", () => ({ useToast: () => ({ toast }) }));

import { usePrintStatus } from "./usePrintStatus";
import { ModelDetail as ModelDetailType } from "../../../api/client";
import { QueryWrapper } from "../../../test/queryWrapper";

const model = { id: 1, print_status: "none", print_count: 0 } as unknown as ModelDetailType;
const printed = { id: 1, print_status: "printed", print_count: 2 } as unknown as ModelDetailType;

beforeEach(() => {
  setPrintStatus.mockClear();
  setPrintStatus.mockResolvedValue({ print_count: 1 });
  toast.mockClear();
});

describe("usePrintStatus", () => {
  it("initializes from the model", () => {
    const { result } = renderHook(() => usePrintStatus(printed, 1), { wrapper: QueryWrapper });
    expect(result.current.printStatus).toBe("printed");
    expect(result.current.printCount).toBe(2);
  });

  it("cycles to the next status and persists, updating the count", async () => {
    const { result } = renderHook(() => usePrintStatus(model, 1), { wrapper: QueryWrapper });
    await act(async () => { await result.current.cyclePrintStatus(); });
    expect(result.current.printStatus).toBe("printed"); // none -> printed
    expect(setPrintStatus).toHaveBeenCalledWith(1, "printed");
    expect(result.current.printCount).toBe(1);
  });

  it("wraps around the cycle from the last status", async () => {
    const queued = { id: 1, print_status: "queued", print_count: 0 } as unknown as ModelDetailType;
    const { result } = renderHook(() => usePrintStatus(queued, 1), { wrapper: QueryWrapper });
    await act(async () => { await result.current.cyclePrintStatus(); });
    expect(result.current.printStatus).toBe("none"); // queued -> none (wrap)
  });

  it("clears the status to none", async () => {
    const { result } = renderHook(() => usePrintStatus(printed, 1), { wrapper: QueryWrapper });
    await act(async () => { await result.current.clearPrintStatus(); });
    expect(result.current.printStatus).toBe("none");
    expect(setPrintStatus).toHaveBeenCalledWith(1, "none");
  });

  it("reverts status and count and toasts on failure", async () => {
    setPrintStatus.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => usePrintStatus(printed, 1), { wrapper: QueryWrapper });
    await act(async () => { await result.current.cyclePrintStatus(); });
    expect(result.current.printStatus).toBe("printed"); // reverted
    expect(result.current.printCount).toBe(2);
    expect(toast).toHaveBeenCalled();
  });
});
