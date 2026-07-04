// Painting-guide server-state hooks (STUDIO-61).
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { queryKeys } from "./keys";

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
