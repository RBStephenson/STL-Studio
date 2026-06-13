import { useEffect, useState } from "react";
import { resolveLibraryKey, nextFocusIndex } from "../utils/libraryKeys";

interface Options {
  /** Number of cards currently in the grid. */
  count: number;
  /** Live column count of the responsive grid (measured from the DOM). */
  getColumns: () => number;
  /** Open the card at the given index. */
  onActivate: (index: number) => void;
  /** Focus (and select) the search input. */
  onFocusSearch: () => void;
  /** Handle Escape: close overlay, blur the search box, or clear focus. */
  onEscape: () => void;
  /** Toggle the shortcuts help overlay. */
  onToggleHelp: () => void;
  enabled?: boolean;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

// Owns the focused-card index and translates global key presses into Library
// actions. See utils/libraryKeys for the pure shortcut logic.
export function useLibraryKeyboard({
  count,
  getColumns,
  onActivate,
  onFocusSearch,
  onEscape,
  onToggleHelp,
  enabled = true,
}: Options) {
  const [focusedIndex, setFocusedIndex] = useState(-1);

  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      const action = resolveLibraryKey(e, isEditableTarget(e.target));
      if (!action) return;
      switch (action.type) {
        case "focusSearch":
          e.preventDefault();
          onFocusSearch();
          break;
        case "help":
          e.preventDefault();
          onToggleHelp();
          break;
        case "escape":
          onEscape();
          break;
        case "activate":
          if (focusedIndex >= 0 && focusedIndex < count) {
            e.preventDefault();
            onActivate(focusedIndex);
          }
          break;
        case "move":
          e.preventDefault();
          setFocusedIndex((cur) =>
            nextFocusIndex(cur, count, getColumns(), action.dCol, action.dRow),
          );
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [enabled, count, getColumns, onActivate, onFocusSearch, onEscape, onToggleHelp, focusedIndex]);

  return { focusedIndex, setFocusedIndex };
}
