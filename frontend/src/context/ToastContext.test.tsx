import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider, useToast } from "./ToastContext";

function Trigger() {
  const { toast } = useToast();
  return <button onClick={() => toast("hello", "info")}>fire</button>;
}

describe("ToastProvider timer cleanup (STUDIO-93)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("clears the pending auto-dismiss timer on manual dismiss", async () => {
    const user = userEvent.setup();
    const clearSpy = vi.spyOn(window, "clearTimeout");

    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );

    await user.click(screen.getByText("fire"));
    expect(screen.getByText("hello")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByText("hello")).not.toBeInTheDocument();
    // The auto-dismiss setTimeout for this toast must be cleared, not left to
    // fire later against an already-removed toast.
    expect(clearSpy).toHaveBeenCalled();
  });

  it("clears all pending toast timers on provider unmount", async () => {
    const user = userEvent.setup();
    const clearSpy = vi.spyOn(window, "clearTimeout");

    const { unmount } = render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );

    await user.click(screen.getByText("fire"));
    expect(screen.getByText("hello")).toBeInTheDocument();

    clearSpy.mockClear();
    unmount();

    // The still-pending auto-dismiss timer must be cleared by the provider's
    // own unmount cleanup, not left to fire setState on a gone component.
    expect(clearSpy).toHaveBeenCalled();
  });

  it("auto-dismiss still fires normally for an active provider", () => {
    vi.useFakeTimers();

    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByText("fire"));
    expect(screen.getByText("hello")).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.queryByText("hello")).not.toBeInTheDocument();
  });
});
