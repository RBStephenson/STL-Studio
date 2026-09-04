import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useSettingsFlash } from "./useSettingsFlash";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useSettingsFlash", () => {
  it("clears the success message after 3s", () => {
    const { result } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("Saved.", "ok"));
    expect(result.current.success).toBe("Saved.");

    act(() => void vi.advanceTimersByTime(3000));
    expect(result.current.success).toBeNull();
  });

  it("clears the error message after 4s", () => {
    const { result } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("Nope.", "err"));
    expect(result.current.error).toBe("Nope.");

    act(() => void vi.advanceTimersByTime(4000));
    expect(result.current.error).toBeNull();
  });

  // The regression guard for the two-ref shape. A single shared timer ref would
  // let the error flash cancel the success clear and strand "Saved." on screen.
  it("clears success and error on independent schedules", () => {
    const { result } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("Saved.", "ok"));
    act(() => void vi.advanceTimersByTime(1000));
    act(() => result.current.flash("Nope.", "err"));

    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current.success).toBeNull();
    expect(result.current.error).toBe("Nope.");

    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current.error).toBeNull();
  });

  it("does not stack timers when the same channel flashes repeatedly", () => {
    const { result } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("First.", "ok"));
    act(() => result.current.flash("Second.", "ok"));
    expect(vi.getTimerCount()).toBe(1);

    // The countdown restarts from the second flash rather than expiring on the
    // first one's schedule.
    act(() => void vi.advanceTimersByTime(2999));
    expect(result.current.success).toBe("Second.");
    act(() => void vi.advanceTimersByTime(1));
    expect(result.current.success).toBeNull();
  });

  // STUDIO-349. Asserted on the pending-timer delta at unmount, before any
  // advance: after advancing, the count is zero whether or not the timer was
  // cleared, which is exactly the assertion that passed against broken code
  // during STUDIO-348 and proved nothing.
  it("clears a pending success timer on unmount", () => {
    const { result, unmount } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("Saved.", "ok"));
    const pending = vi.getTimerCount();
    expect(pending).toBeGreaterThan(0);

    unmount();
    expect(vi.getTimerCount()).toBe(pending - 1);
  });

  it("clears a pending error timer on unmount", () => {
    const { result, unmount } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("Nope.", "err"));
    const pending = vi.getTimerCount();
    expect(pending).toBeGreaterThan(0);

    unmount();
    expect(vi.getTimerCount()).toBe(pending - 1);
  });

  it("clears both pending timers on unmount", () => {
    const { result, unmount } = renderHook(() => useSettingsFlash());

    act(() => result.current.flash("Saved.", "ok"));
    act(() => result.current.flash("Nope.", "err"));
    const pending = vi.getTimerCount();
    expect(pending).toBe(2);

    unmount();
    expect(vi.getTimerCount()).toBe(pending - 2);
  });
});
