// Keyboard-shortcut logic for the Library grid (#169), kept pure so it can be
// unit-tested without a DOM. The hook in useLibraryKeyboard wires these to
// real key events and React state.
//
// Movement uses WASD (with arrow keys as aliases): a/d move left/right within
// the grid, w/s move up/down a row. Up/down needs the live column count, so the
// resolver only reports a direction and nextFocusIndex does the arithmetic.

export type LibraryKeyAction =
  | { type: "focusSearch" }
  | { type: "move"; dCol: number; dRow: number }
  | { type: "activate" }
  | { type: "escape" }
  | { type: "help" }
  | null;

interface KeyEventLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
}

export function resolveLibraryKey(e: KeyEventLike, inEditable: boolean): LibraryKeyAction {
  // Escape is always handled — it blurs the search box, closes the overlay, or
  // clears card focus, even while typing.
  if (e.key === "Escape") return { type: "escape" };

  // Never hijack typing or browser/OS chords (Ctrl/Cmd/Alt combos).
  if (inEditable || e.ctrlKey || e.metaKey || e.altKey) return null;

  switch (e.key) {
    case "/":
      return { type: "focusSearch" };
    case "?":
      return { type: "help" };
    case "Enter":
      return { type: "activate" };
    case "a":
    case "A":
    case "ArrowLeft":
      return { type: "move", dCol: -1, dRow: 0 };
    case "d":
    case "D":
    case "ArrowRight":
      return { type: "move", dCol: 1, dRow: 0 };
    case "w":
    case "W":
    case "ArrowUp":
      return { type: "move", dCol: 0, dRow: -1 };
    case "s":
    case "S":
    case "ArrowDown":
      return { type: "move", dCol: 0, dRow: 1 };
    default:
      return null;
  }
}

// Compute the next focused card index. The first move from "no focus" (-1)
// lands on the first card regardless of direction. Moves that would leave the
// grid are no-ops (stay put) rather than wrapping.
export function nextFocusIndex(
  current: number,
  count: number,
  columns: number,
  dCol: number,
  dRow: number,
): number {
  if (count === 0) return -1;
  if (current < 0) return 0;
  const cols = Math.max(1, columns);
  const delta = dCol !== 0 ? dCol : dRow * cols;
  const next = current + delta;
  return next < 0 || next >= count ? current : next;
}
