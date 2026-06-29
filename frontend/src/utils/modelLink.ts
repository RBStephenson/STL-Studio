import { Model } from "../api/client";

// The Library card and the keyboard "open" action must route to the same place:
// a multi-variant group goes to its group page, everything else to the model.
export function modelLinkTo(model: Model): string {
  const isGroup = (model.variant_count ?? 1) > 1;
  if (isGroup && model.creator_id && model.character) {
    const base = `/groups/${model.creator_id}/${encodeURIComponent(model.character)}`;
    return model.variant_group_id ? `${base}?gid=${model.variant_group_id}` : base;
  }
  return `/models/${model.id}`;
}
