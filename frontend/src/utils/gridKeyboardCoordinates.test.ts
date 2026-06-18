import { describe, it, expect, vi } from "vitest";
import { KeyboardCode } from "@dnd-kit/core";
import { gridKeyboardCoordinates } from "./gridKeyboardCoordinates";

// A 2x2 grid of 100x100 cards (10px gutter). Centers:
//   1 (0,0)→(50,50)   2 (110,0)→(160,50)
//   3 (0,110)→(50,160) 4 (110,110)→(160,160)
const rects = new Map<string, any>([
  ["1", { left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100 }],
  ["2", { left: 110, top: 0, width: 100, height: 100, right: 210, bottom: 100 }],
  ["3", { left: 0, top: 110, width: 100, height: 100, right: 100, bottom: 210 }],
  ["4", { left: 110, top: 110, width: 100, height: 100, right: 210, bottom: 210 }],
]);

function args(activeId: string) {
  return {
    active: { id: activeId },
    currentCoordinates: { x: 0, y: 0 },
    context: {
      active: { id: activeId },
      collisionRect: rects.get(activeId),
      droppableRects: rects,
      droppableContainers: {
        getEnabled: () => [...rects.keys()].map((id) => ({ id })),
      },
    },
  } as any;
}

function arrow(code: KeyboardCode) {
  return { code, preventDefault: vi.fn() } as unknown as KeyboardEvent;
}

describe("gridKeyboardCoordinates (#139)", () => {
  it("ignores non-arrow keys", () => {
    expect(gridKeyboardCoordinates(arrow(KeyboardCode.Space), args("1"))).toBeUndefined();
  });

  it("moves right to the nearest droppable center", () => {
    // From card 1 (center 50,50) → card 2 (center 160,50).
    expect(gridKeyboardCoordinates(arrow(KeyboardCode.Right), args("1"))).toEqual({ x: 160, y: 50 });
  });

  it("moves down to the nearest droppable center", () => {
    // From card 1 → card 3 (center 50,160).
    expect(gridKeyboardCoordinates(arrow(KeyboardCode.Down), args("1"))).toEqual({ x: 50, y: 160 });
  });

  it("returns undefined when no droppable lies in the pressed direction", () => {
    // Card 1 is top-left; nothing is up or left of it.
    expect(gridKeyboardCoordinates(arrow(KeyboardCode.Up), args("1"))).toBeUndefined();
    expect(gridKeyboardCoordinates(arrow(KeyboardCode.Left), args("1"))).toBeUndefined();
  });

  it("never targets the active card itself", () => {
    // From card 4, moving up must pick card 2, not stay on 4.
    expect(gridKeyboardCoordinates(arrow(KeyboardCode.Up), args("4"))).toEqual({ x: 160, y: 50 });
  });

  it("calls preventDefault on arrow keys to stop grid scroll", () => {
    const ev = arrow(KeyboardCode.Down);
    gridKeyboardCoordinates(ev, args("1"));
    expect(ev.preventDefault).toHaveBeenCalled();
  });
});
