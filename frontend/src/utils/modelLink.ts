import { Model } from "../api/client";

// The Library card and the keyboard "open" action must route to the same place:
// a multi-variant group goes to its group page, everything else to the model.
export function modelLinkTo(model: Model): string {
  const isGroup = (model.variant_count ?? 1) > 1;
  const groupLabel = model.variant_group?.label || model.character || model.title || model.name;
  if (isGroup && model.creator_id && groupLabel) {
    const base = `/groups/${model.creator_id}/${encodeURIComponent(groupLabel)}`;
    return model.variant_group_id ? `${base}?gid=${model.variant_group_id}` : base;
  }
  return `/models/${model.id}`;
}
