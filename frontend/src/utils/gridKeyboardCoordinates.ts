import { KeyboardCode, KeyboardCoordinateGetter } from "@dnd-kit/core";

// Free-draggable grid coordinate getter for the keyboard sensor (#139).
//
// The Library cards are free draggables (not a sortable list), so the default
// KeyboardSensor — which nudges by a fixed pixel step — can't hop between cards.
// On an arrow key we instead snap the synthetic pointer to the CENTER of the
// nearest droppable in the pressed direction. Returning the target's center
// (rather than its top-left) keeps `pointerWithin` collision detection robust,
// so keyboard drags resolve `over` exactly like pointer drags do.
const ARROW_CODES: string[] = [
  KeyboardCode.Down,
  KeyboardCode.Up,
  KeyboardCode.Left,
  KeyboardCode.Right,
];

export const gridKeyboardCoordinates: KeyboardCoordinateGetter = (
  event,
  { currentCoordinates, context: { active, collisionRect, droppableContainers, droppableRects } },
) => {
  if (!ARROW_CODES.includes(event.code)) return undefined;
  // Stop the arrow keys from scrolling the grid while a card is picked up.
  event.preventDefault();

  const origin = collisionRect
    ? {
        x: collisionRect.left + collisionRect.width / 2,
        y: collisionRect.top + collisionRect.height / 2,
      }
    : currentCoordinates;

  let best: { x: number; y: number; dist: number } | null = null;
  for (const entry of droppableContainers.getEnabled()) {
    if (active && entry.id === active.id) continue;
    const rect = droppableRects.get(entry.id);
    if (!rect) continue;

    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;

    // Only consider droppables that lie in the pressed direction.
    if (event.code === KeyboardCode.Down && cy <= origin.y) continue;
    if (event.code === KeyboardCode.Up && cy >= origin.y) continue;
    if (event.code === KeyboardCode.Right && cx <= origin.x) continue;
    if (event.code === KeyboardCode.Left && cx >= origin.x) continue;

    const dist = Math.hypot(cx - origin.x, cy - origin.y);
    if (!best || dist < best.dist) best = { x: cx, y: cy, dist };
  }

  return best ? { x: best.x, y: best.y } : undefined;
};
