// Shared tag presentation for anything that renders a model's tag chips —
// the Library card and the variant side panel (STUDIO-350). Extracted so the
// colour map and the auto-tag merge rule live in one place rather than drifting
// between the two surfaces.

import { Model } from "../api/client";

export const TAG_COLORS: Record<string, string> = {
  "pre-supported": "bg-emerald-900 text-emerald-300",
  "bust":          "bg-blue-900 text-blue-300",
  "statue":        "bg-purple-900 text-purple-300",
  "figure":        "bg-indigo-900 text-indigo-300",
};

export function tagClass(tag: string): string {
  return TAG_COLORS[tag] ?? "bg-panel-secondary text-text-secondary";
}

/**
 * The tags a model actually shows: scanner auto-tags the user hasn't removed,
 * followed by their own tags, de-duplicated and order-stable.
 *
 * `ownTags` lets a caller pass optimistic local state (the card keeps its own
 * copy while a tag edit is in flight); omit it to use the model's persisted tags.
 */
export function visibleTags(model: Model, ownTags?: string[]): string[] {
  const removedAuto = new Set(model.removed_auto_tags ?? []);
  const autoTags = (model.auto_tags ?? []).filter((t) => !removedAuto.has(t));
  return [...new Set([...autoTags, ...(ownTags ?? model.tags ?? [])])];
}
