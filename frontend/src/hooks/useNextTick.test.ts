import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useNextTick } from "./useNextTick";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useNextTick", () => {
  it("runs the callback on the next tick, not synchronously", () => {
    const fn = vi.fn();
    const { result } = renderHook(() => useNextTick());

    act(() => result.current(fn));
    expect(fn).not.toHaveBeenCalled();

    act(() => void vi.advanceTimersByTime(0));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("replaces a pending callback rather than stacking a second timer", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result } = renderHook(() => useNextTick());

    act(() => {
      result.current(first);
      result.current(second);
    });
    expect(vi.getTimerCount()).toBe(1);

    act(() => void vi.advanceTimersByTime(0));
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  // STUDIO-349. Checked on the pending count at unmount and on the callback
  // never firing — asserting only after the advance would pass either way.
  it("cancels a pending callback on unmount", () => {
    const fn = vi.fn();
    const { result, unmount } = renderHook(() => useNextTick());

    act(() => result.current(fn));
    const pending = vi.getTimerCount();
    expect(pending).toBeGreaterThan(0);

    unmount();
    expect(vi.getTimerCount()).toBe(pending - 1);

    vi.advanceTimersByTime(0);
    expect(fn).not.toHaveBeenCalled();
  });

  it("keeps a stable identity across renders so it is dependency-safe", () => {
    const { result, rerender } = renderHook(() => useNextTick());
    const first = result.current;

    rerender();
    expect(result.current).toBe(first);
  });
});
