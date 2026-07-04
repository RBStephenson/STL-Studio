import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";

const updateSettings = vi.fn(async () => {});
let librarySort = "name";

vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: { library_page_size: 60, library_sort: librarySort },
    update: updateSettings,
  }),
}));

import { useLibraryFilters } from "./useLibraryFilters";

const wrapper = (initial: string) =>
  ({ children }: { children: ReactNode }) =>
    <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>;

beforeEach(() => {
  updateSettings.mockClear();
  librarySort = "name";
});

describe("useLibraryFilters", () => {
  it("derives typed filter values from the query string", () => {
    const { result } = renderHook(() => useLibraryFilters(), {
      wrapper: wrapper("/?q=knight&creator_id=5&is_favorite=1&page=2"),
    });
    expect(result.current.page).toBe(2);
    expect(result.current.creatorId).toBe("5");
    expect(result.current.favParam).toBe(true);
    expect(result.current.searchInput).toBe("knight");
  });

  it("builds listParams including page_size and only the active filters", () => {
    const { result } = renderHook(() => useLibraryFilters(), {
      wrapper: wrapper("/?tag=dragon"),
    });
    expect(result.current.listParams).toMatchObject({
      page: 1, page_size: 60, group_variants: true, tag: "dragon",
    });
    expect(result.current.listParams).not.toHaveProperty("creator_id");
  });

  it("setParam writes the value and resets to page 1", () => {
    const { result } = renderHook(() => useLibraryFilters(), {
      wrapper: wrapper("/?page=3"),
    });
    act(() => { result.current.setParam("source_site", "thingiverse"); });
    expect(result.current.site).toBe("thingiverse");
    expect(result.current.page).toBe(1); // page dropped
  });

  it("disables group_variants when filtering by favorites", () => {
    const { result } = renderHook(() => useLibraryFilters(), {
      wrapper: wrapper("/?is_favorite=1"),
    });
    expect(result.current.listParams.group_variants).toBe(false);
  });

  it("debounces the search input into the q param", async () => {
    const { result } = renderHook(() => useLibraryFilters(), { wrapper: wrapper("/") });
    act(() => { result.current.onSearchChange("mecha"); });
    expect(result.current.searchInput).toBe("mecha"); // instant local
    await waitFor(() => expect(result.current.listParams.q).toBe("mecha"), { timeout: 1000 });
  });

  it("changeSort persists the default and mirrors it to the URL", () => {
    const { result } = renderHook(() => useLibraryFilters(), { wrapper: wrapper("/") });
    act(() => { result.current.changeSort("added"); });
    expect(updateSettings).toHaveBeenCalledWith({ library_sort: "added" });
    expect(result.current.effectiveSort).toBe("added");
  });

  it("addedDays forces the 'added' sort regardless of sort param", () => {
    const { result } = renderHook(() => useLibraryFilters(), {
      wrapper: wrapper("/?added_days=7&sort=name"),
    });
    expect(result.current.effectiveSort).toBe("added");
    expect(result.current.listParams.added_within_days).toBe("7");
  });
});
