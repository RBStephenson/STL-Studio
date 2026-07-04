// Collections server-state hooks (STUDIO-61).
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Collection } from "../../api/client";
import { queryKeys } from "./keys";

export function useCollections() {
  return useQuery<Collection[]>({
    queryKey: queryKeys.collections.all,
    queryFn: () => api.collections.list(),
  });
}
