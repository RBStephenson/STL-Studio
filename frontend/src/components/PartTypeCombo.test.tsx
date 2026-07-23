import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PartTypeCombo } from "./PartTypeCombo";

const OPTIONS = ["Weapon", "Accessories", "Base", "Arms"];

function mockRect(overrides: Partial<DOMRect>): DOMRect {
  return {
    x: 0, y: 0, width: 100, height: 20,
    top: 0, left: 0, right: 100, bottom: 20,
    toJSON: () => ({}),
    ...overrides,
  } as DOMRect;
}

describe("PartTypeCombo", () => {
  it("lists options alphabetically regardless of the source array's order", () => {
    render(<PartTypeCombo value="" options={OPTIONS} onChange={vi.fn()} onCommit={vi.fn()} />);
    fireEvent.focus(screen.getByRole("textbox"));
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["Accessories", "Arms", "Base", "Weapon"]);
  });

  it("opens below the field when there's enough room", () => {
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    render(<PartTypeCombo value="" options={OPTIONS} onChange={vi.fn()} onCommit={vi.fn()} />);
    const input = screen.getByRole("textbox");
    vi.spyOn(input, "getBoundingClientRect").mockReturnValue(mockRect({ top: 100, bottom: 120 }));
    fireEvent.focus(input);

    const list = screen.getByRole("list");
    expect(list.style.top).toBe("122px");
    expect(list.style.bottom).toBe("");
  });

  it("flips above the field when there isn't enough room below, so it's never clipped", () => {
    Object.defineProperty(window, "innerHeight", { value: 300, configurable: true });
    render(<PartTypeCombo value="" options={OPTIONS} onChange={vi.fn()} onCommit={vi.fn()} />);
    const input = screen.getByRole("textbox");
    // Field sits near the bottom of a short viewport: little room below, plenty above.
    vi.spyOn(input, "getBoundingClientRect").mockReturnValue(mockRect({ top: 260, bottom: 280 }));
    fireEvent.focus(input);

    const list = screen.getByRole("list");
    expect(list.style.top).toBe("");
    expect(list.style.bottom).toBe(`${300 - 260 + 2}px`);
  });

  it("does not close the list after unmount when blurred moments before (STUDIO-348)", () => {
    vi.useFakeTimers();
    try {
      const { unmount } = render(
        <PartTypeCombo value="" options={OPTIONS} onChange={vi.fn()} onCommit={vi.fn()} />,
      );
      fireEvent.focus(screen.getByRole("textbox"));
      fireEvent.blur(screen.getByRole("textbox"));
      expect(vi.getTimerCount()).toBe(1);

      unmount();

      // Must be cleared by unmount, not merely harmless once it fires: left
      // pending it calls setOpen on a dead component, and under jsdom that
      // lands after teardown as React dereferencing a gone window — an
      // unhandled error that fails the entire test run.
      expect(vi.getTimerCount()).toBe(0);
      expect(() => vi.advanceTimersByTime(500)).not.toThrow();
    } finally {
      vi.useRealTimers();
    }
  });

  it("still closes the list shortly after blur while mounted", () => {
    vi.useFakeTimers();
    try {
      render(<PartTypeCombo value="" options={OPTIONS} onChange={vi.fn()} onCommit={vi.fn()} />);
      fireEvent.focus(screen.getByRole("textbox"));
      expect(screen.getByRole("list")).toBeInTheDocument();

      fireEvent.blur(screen.getByRole("textbox"));
      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(screen.queryByRole("list")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("commits on blur", () => {
    const onCommit = vi.fn();
    render(<PartTypeCombo value="Base" options={OPTIONS} onChange={vi.fn()} onCommit={onCommit} />);

    fireEvent.blur(screen.getByRole("textbox"));

    expect(onCommit).toHaveBeenCalledWith("Base");
  });

  it("commits the picked option and closes the list", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(<PartTypeCombo value="" options={OPTIONS} onChange={onChange} onCommit={onCommit} />);
    fireEvent.focus(screen.getByRole("textbox"));

    fireEvent.mouseDown(screen.getByText("Base"));

    expect(onChange).toHaveBeenCalledWith("Base");
    expect(onCommit).toHaveBeenCalledWith("Base");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
