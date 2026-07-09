import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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
