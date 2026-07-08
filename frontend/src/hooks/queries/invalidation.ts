import type { QueryClient } from "@tanstack/react-query";
import { queryKeys } from "./keys";

interface ModelInvalidationOptions {
  modelId?: number;
  includeLists?: boolean;
  includeStats?: boolean;
  includeVariants?: boolean;
}

export function invalidateModelViews(
  queryClient: QueryClient,
  {
    modelId,
    includeLists = true,
    includeStats = true,
    includeVariants = true,
  }: ModelInvalidationOptions = {},
) {
  if (modelId != null) {
    queryClient.invalidateQueries({ queryKey: queryKeys.models.detail(modelId) });
  }
  if (includeLists) {
    queryClient.invalidateQueries({ queryKey: queryKeys.models.listAll });
  }
  if (includeStats) {
    queryClient.invalidateQueries({ queryKey: queryKeys.models.stats });
  }
  if (includeVariants) {
    queryClient.invalidateQueries({ queryKey: queryKeys.models.variantsAll });
  }
}
