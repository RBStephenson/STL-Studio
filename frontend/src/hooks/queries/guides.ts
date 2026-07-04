// Painting-guide server-state hooks (STUDIO-61).
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { queryKeys } from "./keys";

// Set of model ids that have a painting guide → "Guide" badge in the Library
// grid (#263). Gated on the painting module being enabled; returns an empty set
// when off so callers can read it unconditionally.
export function useGuideModelIds(enabled: boolean) {
  return useQuery<Set<number>>({
    queryKey: queryKeys.guides.modelIds,
    queryFn: async () => new Set((await api.painting.guides.modelIds()).model_ids),
    enabled,
  });
}

// Resolve whether a model has a painting guide (#263). Returns the guide id or
// null. Gated on the caller passing enabled (the painting_guides_enabled module
// flag) so no request fires when the feature is off.
export function useModelGuideId(modelId: number | undefined, enabled: boolean) {
  return useQuery<number | null>({
    queryKey: queryKeys.guides.forModel(modelId ?? -1),
    queryFn: async () => {
      const r = await api.painting.guides.list({ model_id: modelId!, page_size: 1 });
      return r.items[0]?.id ?? null;
    },
    enabled: enabled && modelId != null,
  });
}
