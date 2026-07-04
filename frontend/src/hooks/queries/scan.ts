// Scan-config / drive-status server-state hooks (STUDIO-61).
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { queryKeys } from "./keys";

// How many scan roots are configured — drives the first-run onboarding card.
// null on error, matching the pre-migration fallback.
export function useScanRootCount() {
  return useQuery<number | null>({
    queryKey: queryKeys.scan.roots,
    queryFn: async () => (await api.scan.roots()).length,
  });
}

// Configured roots that are currently unavailable (unmounted/disconnected).
export function useUnavailableRoots() {
  return useQuery<string[]>({
    queryKey: queryKeys.scan.driveStatus,
    queryFn: async () => {
      const s = await api.files.driveStatus();
      return s.roots.filter((r) => r.enabled && !r.available).map((r) => r.path);
    },
  });
}
