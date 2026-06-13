import { describe, it, expect } from "vitest";
import { resolveLibraryKey, nextFocusIndex, LibraryKeyAction } from "./libraryKeys";

const ev = (key: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  ...mods,
});

describe("resolveLibraryKey (#169)", () => {
  it("maps the movement keys to WASD + arrow deltas", () => {
    const cases: [string, LibraryKeyAction][] = [
      ["a", { type: "move", dCol: -1, dRow: 0 }],
      ["d", { type: "move", dCol: 1, dRow: 0 }],
      ["w", { type: "move", dCol: 0, dRow: -1 }],
      ["s", { type: "move", dCol: 0, dRow: 1 }],
      ["ArrowLeft", { type: "move", dCol: -1, dRow: 0 }],
      ["ArrowRight", { type: "move", dCol: 1, dRow: 0 }],
      ["ArrowUp", { type: "move", dCol: 0, dRow: -1 }],
      ["ArrowDown", { type: "move", dCol: 0, dRow: 1 }],
    ];
    for (const [key, expected] of cases) {
      expect(resolveLibraryKey(ev(key), false)).toEqual(expected);
    }
  });

  it("maps the action keys", () => {
    expect(resolveLibraryKey(ev("/"), false)).toEqual({ type: "focusSearch" });
    expect(resolveLibraryKey(ev("?"), false)).toEqual({ type: "help" });
    expect(resolveLibraryKey(ev("Enter"), false)).toEqual({ type: "activate" });
    expect(resolveLibraryKey(ev("Escape"), false)).toEqual({ type: "escape" });
  });

  it("ignores keys while typing, except Escape", () => {
    // Movement / action keys are suppressed inside an editable target…
    expect(resolveLibraryKey(ev("a"), true)).toBeNull();
    expect(resolveLibraryKey(ev("/"), true)).toBeNull();
    expect(resolveLibraryKey(ev("Enter"), true)).toBeNull();
    // …but Escape always works so the user can blur the search box.
    expect(resolveLibraryKey(ev("Escape"), true)).toEqual({ type: "escape" });
  });

  it("never hijacks browser/OS chords", () => {
    expect(resolveLibraryKey(ev("d", { ctrlKey: true }), false)).toBeNull();
    expect(resolveLibraryKey(ev("a", { metaKey: true }), false)).toBeNull();
    expect(resolveLibraryKey(ev("s", { altKey: true }), false)).toBeNull();
  });

  it("returns null for unmapped keys", () => {
    expect(resolveLibraryKey(ev("x"), false)).toBeNull();
    expect(resolveLibraryKey(ev("Tab"), false)).toBeNull();
  });
});

describe("nextFocusIndex (#169)", () => {
  it("focuses the first card on the first move from no focus", () => {
    expect(nextFocusIndex(-1, 10, 4, -1, 0)).toBe(0);
    expect(nextFocusIndex(-1, 10, 4, 0, 1)).toBe(0);
  });

  it("moves horizontally by one and vertically by a row", () => {
    expect(nextFocusIndex(5, 12, 4, 1, 0)).toBe(6); // right
    expect(nextFocusIndex(5, 12, 4, -1, 0)).toBe(4); // left
    expect(nextFocusIndex(5, 12, 4, 0, 1)).toBe(9); // down a row
    expect(nextFocusIndex(5, 12, 4, 0, -1)).toBe(1); // up a row
  });

  it("stays put rather than leaving the grid", () => {
    expect(nextFocusIndex(0, 12, 4, -1, 0)).toBe(0); // left edge
    expect(nextFocusIndex(11, 12, 4, 1, 0)).toBe(11); // right edge
    expect(nextFocusIndex(1, 12, 4, 0, -1)).toBe(1); // top row, up
    expect(nextFocusIndex(10, 12, 4, 0, 1)).toBe(10); // bottom row, down
  });

  it("returns -1 for an empty grid", () => {
    expect(nextFocusIndex(-1, 0, 4, 0, 1)).toBe(-1);
  });
});
