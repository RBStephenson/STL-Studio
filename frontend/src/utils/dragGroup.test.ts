import { describe, it, expect } from "vitest";
import { resolveDragIntent, type DragCard } from "./dragGroup";

const cards: Record<number, DragCard> = {
  1: { id: 1, creator_id: 10, name: "Goblin A", title: "Goblin A" },
  2: { id: 2, creator_id: 10, name: "Goblin B", title: "Goblin B" },
  3: { id: 3, creator_id: 10, name: "Goblin", title: "Goblin", character: "Goblin", variant_count: 4 },
  4: { id: 4, creator_id: 99, name: "Other-creator model" },
  5: { id: 5, creator_id: 10, name: "Orc", title: "Orc", character: "Orc", variant_count: 2 },
};
const byId = (id: number) => cards[id];
const sel = (...ids: number[]) => new Set(ids);

describe("resolveDragIntent", () => {
  it("no-ops on self-drop or unknown cards", () => {
    expect(resolveDragIntent(1, 1, byId, sel()).kind).toBe("none");
    expect(resolveDragIntent(1, 404, byId, sel()).kind).toBe("none");
  });

  it("single drag onto an ungrouped target prompts with the target's name", () => {
    const intent = resolveDragIntent(1, 2, byId, sel());
    expect(intent).toEqual({
      kind: "prompt",
      sourceIds: [1],
      targetId: 2,
      suggestedName: "Goblin B",
      skipped: 0,
    });
  });

  it("single drag onto an existing group applies that group's character", () => {
    const intent = resolveDragIntent(1, 3, byId, sel());
    expect(intent).toEqual({ kind: "apply", sourceIds: [1], character: "Goblin", skipped: 0 });
  });

  it("#137 — dragging a selected card moves the whole selection", () => {
    const intent = resolveDragIntent(1, 3, byId, sel(1, 2));
    expect(intent).toEqual({ kind: "apply", sourceIds: [1, 2], character: "Goblin", skipped: 0 });
  });

  it("#137 — a non-selected drag ignores the selection and moves only itself", () => {
    const intent = resolveDragIntent(1, 3, byId, sel(2, 5));
    expect(intent).toMatchObject({ kind: "apply", sourceIds: [1] });
  });

  it("#137 — cross-creator members in the selection are skipped, not moved", () => {
    const intent = resolveDragIntent(1, 3, byId, sel(1, 2, 4));
    expect(intent).toEqual({ kind: "apply", sourceIds: [1, 2], character: "Goblin", skipped: 1 });
  });

  it("errors when a single drop crosses creators", () => {
    const intent = resolveDragIntent(4, 1, byId, sel());
    expect(intent.kind).toBe("error");
  });

  it("#136 — dragging a group defers to a confirm step", () => {
    const intent = resolveDragIntent(3, 1, byId, sel());
    expect(intent).toEqual({ kind: "group-merge", sourceId: 3, targetId: 1 });
  });

  it("#136 — group merge across creators is rejected", () => {
    const cross: Record<number, DragCard> = {
      ...cards,
      6: { id: 6, creator_id: 10, name: "x", character: "x", variant_count: 3 },
    };
    const intent = resolveDragIntent(6, 4, (id) => cross[id], sel());
    expect(intent.kind).toBe("error");
  });
});
