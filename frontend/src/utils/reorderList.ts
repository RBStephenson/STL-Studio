// Move the item with id `activeId` to the position of `overId`, returning the
// new id order (#399 variant drag-reorder). Pure so the drag logic is testable
// without a DOM. Unknown ids or a no-op move return the input order unchanged.
export function reorderedIds(ids: number[], activeId: number, overId: number): number[] {
  const from = ids.indexOf(activeId);
  const to = ids.indexOf(overId);
  if (from === -1 || to === -1 || from === to) return ids;
  const next = ids.slice();
  next.splice(from, 1);
  next.splice(to, 0, activeId);
  return next;
}
