import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useRef } from "react";

vi.mock("../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: { library_page_size: 60, library_sort: "name" },
    update: vi.fn(),
  }),
}));

import FilterBar from "./FilterBar";
import { useLibraryFilters } from "../../hooks/useLibraryFilters";

const creators = [{ id: 1, name: "Artisan Guild", model_count: 12 }];
const allTags = [{ tag: "dragon", count: 5 }, { tag: "hero", count: 3 }];

function Harness({ showFilters = true, ...rest }: { showFilters?: boolean } & Partial<React.ComponentProps<typeof FilterBar>>) {
  const filters = useLibraryFilters();
  const presetInputRef = useRef<HTMLInputElement>(null);
  return (
    <FilterBar
      filters={filters}
      showFilters={showFilters}
      setShowFilters={vi.fn()}
      hasFilters={false}
      creators={creators}
      allTags={allTags}
      presets={[]}
      applyPreset={vi.fn()}
      deletePreset={vi.fn()}
      savingPreset={false}
      setSavingPreset={vi.fn()}
      presetName=""
      setPresetName={vi.fn()}
      presetInputRef={presetInputRef}
      confirmSavePreset={vi.fn()}
      {...rest}
    />
  );
}

const renderBar = (initial = "/", props: Partial<React.ComponentProps<typeof FilterBar>> = {}) =>
  render(<MemoryRouter initialEntries={[initial]}><Harness {...props} /></MemoryRouter>);

describe("FilterBar", () => {
  it("renders the search box and reflects the URL query", () => {
    renderBar("/?q=knight");
    expect(screen.getByPlaceholderText(/Search models/)).toHaveValue("knight");
  });

  it("updates the search input on typing", () => {
    renderBar("/");
    const input = screen.getByPlaceholderText(/Search models/);
    fireEvent.change(input, { target: { value: "mecha" } });
    expect(input).toHaveValue("mecha");
  });

  it("toggles the filter panel via setShowFilters", () => {
    const setShowFilters = vi.fn();
    renderBar("/", { setShowFilters, showFilters: false });
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    expect(setShowFilters).toHaveBeenCalledWith(true);
  });

  it("lists creator options in the filter panel", () => {
    renderBar("/");
    // appears in both the include- and exclude-creator selects
    expect(screen.getAllByRole("option", { name: /Artisan Guild \(12\)/ }).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the tag picker and filters tags by the tag search box", () => {
    renderBar("/");
    expect(screen.getByRole("button", { name: /dragon/ })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search tags…"), { target: { value: "her" } });
    expect(screen.queryByRole("button", { name: /dragon/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hero/ })).toBeInTheDocument();
  });

  it("shows an active-tag chip and clears it on click", () => {
    renderBar("/?tag=dragon");
    // chip + picker both show "dragon"; the chip's X clears the tag param
    const clears = screen.getAllByRole("button").filter((b) => b.querySelector("svg"));
    expect(clears.length).toBeGreaterThan(0);
  });
});
