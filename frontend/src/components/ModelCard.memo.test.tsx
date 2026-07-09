import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import ModelCard from "./ModelCard";
import { Model } from "../api/client";
import { createTestQueryClient } from "../test/queryWrapper";

// Render counter wired into a child so we can observe how many times the card's
// body actually re-rendered. StarRating renders on every ModelCard render, so its
// call count tracks the card's renders (#382).
let starRenders = 0;
vi.mock("./StarRating", () => ({
  default: () => { starRenders++; return null; },
}));

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("./QuickAssignPopover", () => ({ default: () => null }));

const MODEL = {
  id: 7, name: "robocop", title: "RoboCop", character: null, variant_count: 1,
  nsfw: false, is_favorite: false, needs_review: false,
  print_status: "none", print_count: 0,
  auto_tags: [], tags: [], thumbnail_path: null, thumbnail_url: null,
  rating: null, source_site: null, creator_id: 1,
  created_at: "2020-01-01T00:00:00", updated_at: "2020-01-01T00:00:00",
} as unknown as Model;

describe("ModelCard memoization (#382)", () => {
  beforeEach(() => { starRenders = 0; });

  const wrap = (node: ReactNode) => (
    <QueryClientProvider client={createTestQueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );

  it("does not re-render when props are unchanged", () => {
    // Stable references mirror what the Library passes: useCallback'd handlers and
    // stable state arrays. A parent re-render with identical props must be skipped.
    const onSelect = vi.fn();
    const allTags = [{ tag: "bust", count: 3 }];
    const client = createTestQueryClient();
    const wrapWithStableClient = (node: ReactNode) => (
      <QueryClientProvider client={client}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>
    );
    const card = (
      wrapWithStableClient(
        <ModelCard model={MODEL} selected={false} focused={false} onSelect={onSelect} allTagSuggestions={allTags} />
      )
    );
    const { rerender } = render(card);
    expect(starRenders).toBe(1);

    // Same props, new parent render → memo skips the card.
    rerender(
      wrapWithStableClient(
        <ModelCard model={MODEL} selected={false} focused={false} onSelect={onSelect} allTagSuggestions={allTags} />
      )
    );
    expect(starRenders).toBe(1);
  });

  it("re-renders when selection changes", () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      wrap(<ModelCard model={MODEL} selected={false} onSelect={onSelect} />)
    );
    expect(starRenders).toBe(1);
    rerender(
      wrap(<ModelCard model={MODEL} selected={true} onSelect={onSelect} />)
    );
    expect(starRenders).toBe(2);
  });

  it("re-renders when keyboard focus changes", () => {
    const { rerender } = render(
      wrap(<ModelCard model={MODEL} focused={false} />)
    );
    expect(starRenders).toBe(1);
    rerender(
      wrap(<ModelCard model={MODEL} focused={true} />)
    );
    expect(starRenders).toBe(2);
  });
});
