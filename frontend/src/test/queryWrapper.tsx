// Test helper (STUDIO-61). Components that use TanStack Query hooks must render
// under a QueryClientProvider. Each render gets a fresh client so cache state
// never leaks between tests, and retries/gc are off so failed queries surface
// immediately and don't linger.
import { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  });
}

export function QueryWrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>;
}
