// Model server-state hooks (STUDIO-61). Thin useQuery wrappers over the
// api.models.* fetch layer — the hooks own caching/staleness/refetch, the api
// slice still owns the HTTP. Invalidation keys come from the central factory so
// a mutation can refresh exactly the affected queries.
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Model, ModelDetail } from "../../api/client";
import { queryKeys } from "./keys";

// The Library-origin filter params parsed for the neighbors endpoint. null when
// the model wasn't reached from the Library grid → no Prev/Next.
export type NavOrigin = Record<string, string | number | boolean> | null;

export function useModel(id: number | undefined) {
  return useQuery<ModelDetail>({
    queryKey: queryKeys.models.detail(id ?? -1),
    queryFn: () => api.models.get(id!),
    enabled: id != null,
  });
}

// Sibling variants for the variant switcher. Gated exactly like the old effect:
// needs a creator and either a durable group id (#678, authoritative) or a
// character to match on. Disabled otherwise so no request fires.
export function useModelVariants(model: ModelDetail | null | undefined) {
  const creatorId = model?.creator_id ?? undefined;
  const character = model?.character ?? "";
  const groupId = model?.variant_group_id ?? null;
  const enabled = creatorId != null && (groupId != null || !!model?.character);

  return useQuery<Model[]>({
    queryKey: queryKeys.models.variants(creatorId ?? -1, character, groupId),
    queryFn: async () => (await api.models.variants(creatorId!, character, groupId)).items,
    enabled,
  });
}

// Prev/Next neighbors within the Library ordering the user came from. Disabled
// when navOrigin is null (deep link / group / collection origin).
export function useModelNeighbors(id: number | undefined, navOrigin: NavOrigin) {
  return useQuery<{ prev_id: number | null; next_id: number | null }>({
    queryKey: queryKeys.models.neighbors(id ?? -1, navOrigin ?? {}),
    queryFn: () => api.models.neighbors(id!, navOrigin!),
    enabled: id != null && navOrigin != null,
  });
}
