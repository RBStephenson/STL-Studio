// Pure decision logic for Library drag-to-group (#135/#136/#137). Kept out of the
// component so it can be unit-tested without simulating a dnd-kit drag in jsdom.

export interface DragCard {
  id: number;
  creator_id: number | null;
  variant_count?: number | null;
  character?: string | null;
  title?: string | null;
  name: string;
}

/** What a drop should do, resolved from the dragged card, the drop target, and
 *  the current multi-selection. The component turns this into API calls / modals. */
export type DragIntent =
  // No-op: missing cards, self-drop, or nothing under the pointer.
  | { kind: "none" }
  // Reject with a toast (e.g. cross-creator drop).
  | { kind: "error"; message: string }
  // A whole group was dragged onto a target — confirm, then reassign all members.
  | { kind: "group-merge"; sourceId: number; targetId: number }
  // Target is already a group: apply its character to the sources immediately.
  | { kind: "apply"; sourceIds: number[]; character: string; skipped: number }
  // Target is ungrouped: prompt for a name; the target joins the new group too.
  | { kind: "prompt"; sourceIds: number[]; targetId: number; suggestedName: string; skipped: number };

const CROSS_CREATOR = "Models must be from the same creator to group them.";

/** Resolve a drop into an intent. `byId` looks a card up by id; `selection` is the
 *  current multi-select set. Grouping is per-creator throughout. */
export function resolveDragIntent(
  draggedId: number,
  targetId: number,
  byId: (id: number) => DragCard | undefined,
  selection: ReadonlySet<number>,
): DragIntent {
  if (targetId === draggedId) return { kind: "none" };

  const dragged = byId(draggedId);
  const target = byId(targetId);
  if (!dragged || !target) return { kind: "none" };

  // #136 — dragging a whole group: defer to a confirmation step.
  if ((dragged.variant_count ?? 1) > 1) {
    if (dragged.creator_id !== target.creator_id) {
      return { kind: "error", message: "Groups must share a creator to merge." };
    }
    return { kind: "group-merge", sourceId: draggedId, targetId };
  }

  // #137 — if the grabbed card is part of the multi-selection, move the whole
  // selection; otherwise just the dragged card. Drop any not sharing the target's
  // creator (grouping is per-creator) and report how many were skipped.
  const candidates =
    selection.has(draggedId) && selection.size > 1 ? [...selection] : [draggedId];
  const sourceIds = candidates.filter((id) => byId(id)?.creator_id === target.creator_id);
  if (sourceIds.length === 0) return { kind: "error", message: CROSS_CREATOR };
  const skipped = candidates.length - sourceIds.length;

  if (target.character) {
    return { kind: "apply", sourceIds, character: target.character, skipped };
  }
  return {
    kind: "prompt",
    sourceIds,
    targetId,
    suggestedName: target.title || target.name,
    skipped,
  };
}
