// Shared TanStack Query client (STUDIO-61). The server-state layer for the app:
// hand-rolled fetch + useState/useEffect data flows migrate onto useQuery/
// useMutation hooks (src/hooks/queries/) that read through this client.
//
// retry: false keeps a failed fetch single-shot, so a 404 surfaces immediately
// as "not found" instead of being retried like a transient error — matching the
// pre-migration behavior. refetchOnWindowFocus is off because this is a local
// desktop-style app, not a dashboard that needs to poll on focus.
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});
