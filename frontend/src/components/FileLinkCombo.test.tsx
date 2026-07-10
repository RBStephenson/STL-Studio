import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FileLinkCombo, FileLinkOption } from "./FileLinkCombo";

const OPTIONS: FileLinkOption[] = [
  { id: 1, label: "Right Hand", filename: "hand-r.stl" },
  { id: 2, label: "Left Hand", filename: "hand-l.stl" },
  { id: 3, label: "Head", filename: "head.stl" },
  { id: 4, label: "hand-old.stl", filename: "hand-old.stl" }, // no part_name set — falls back to filename
];

function mockRect(overrides: Partial<DOMRect>): DOMRect {
  return {
    x: 0, y: 0, width: 100, height: 20,
    top: 0, left: 0, right: 100, bottom: 20,
    toJSON: () => ({}),
    ...overrides,
  } as DOMRect;
}

describe("FileLinkCombo", () => {
  it("shows the part-name label, not the filename, as the primary text", () => {
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.focus(screen.getByRole("textbox"));
    expect(screen.getByText("Right Hand")).toBeInTheDocument();
  });

  it("still shows the filename as a secondary hint below the part name", () => {
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.focus(screen.getByRole("textbox"));
    // The filename hint is only rendered when it differs from the label.
    expect(screen.getByText("hand-r.stl")).toBeInTheDocument();
  });

  it("does not duplicate the filename hint when there's no part name to fall back from", () => {
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.focus(screen.getByRole("textbox"));
    expect(screen.getAllByText("hand-old.stl")).toHaveLength(1);
  });

  it("filters by typing, matching either the part name or the filename", () => {
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByRole("textbox");

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "hand" } });
    // Matches "Right Hand", "Left Hand" (label) and "hand-old.stl" (filename fallback label).
    expect(screen.getByText("Right Hand")).toBeInTheDocument();
    expect(screen.getByText("Left Hand")).toBeInTheDocument();
    expect(screen.getByText("hand-old.stl")).toBeInTheDocument();
    expect(screen.queryByText("Head")).not.toBeInTheDocument();
  });

  it("matches on filename even when the part-name label doesn't contain the query", () => {
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "head.stl" } });
    expect(screen.getByText("Head")).toBeInTheDocument();
    expect(screen.queryByText("Right Hand")).not.toBeInTheDocument();
  });

  it("shows a no-matches message instead of an empty list", () => {
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "zzz-nothing-matches" } });
    expect(screen.getByText("No matches")).toBeInTheDocument();
  });

  it("picks an option and does not fire onPick for a disabled one", () => {
    const onPick = vi.fn();
    const options: FileLinkOption[] = [
      { id: 1, label: "Right Hand", filename: "hand-r.stl", disabled: true, suffix: " ✓" },
      { id: 2, label: "Left Hand", filename: "hand-l.stl" },
    ];
    render(<FileLinkCombo options={options} onPick={onPick} onCancel={vi.fn()} />);
    fireEvent.focus(screen.getByRole("textbox"));

    fireEvent.mouseDown(screen.getByText(/Right Hand/));
    expect(onPick).not.toHaveBeenCalled();

    fireEvent.mouseDown(screen.getByText("Left Hand"));
    expect(onPick).toHaveBeenCalledWith(2);
  });

  it("opens below the field when there's enough room", () => {
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByRole("textbox");
    vi.spyOn(input, "getBoundingClientRect").mockReturnValue(mockRect({ top: 100, bottom: 120 }));
    fireEvent.focus(input);

    const list = screen.getByRole("list");
    expect(list.style.top).toBe("122px");
    expect(list.style.bottom).toBe("");
  });

  it("flips above the field when there isn't enough room below", () => {
    Object.defineProperty(window, "innerHeight", { value: 300, configurable: true });
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByRole("textbox");
    vi.spyOn(input, "getBoundingClientRect").mockReturnValue(mockRect({ top: 260, bottom: 280 }));
    fireEvent.focus(input);

    const list = screen.getByRole("list");
    expect(list.style.top).toBe("");
    expect(list.style.bottom).toBe(`${300 - 260 + 2}px`);
  });

  it("calls onCancel on blur (and on Escape) so the caller can close the picker", () => {
    vi.useFakeTimers();
    const onCancel = vi.fn();
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={onCancel} />);
    fireEvent.blur(screen.getByRole("textbox"));
    vi.advanceTimersByTime(200);
    expect(onCancel).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("calls onCancel immediately on Escape", () => {
    const onCancel = vi.fn();
    render(<FileLinkCombo options={OPTIONS} onPick={vi.fn()} onCancel={onCancel} />);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });
});
