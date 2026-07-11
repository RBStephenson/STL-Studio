import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  api: { fileUrl: (p: string) => p },
}));
vi.mock("../../components/ModelCard", () => ({
  default: ({ model }: { model: { id: number; name: string } }) => (
    <div data-testid="model-card">{model.name}</div>
  ),
}));

import ModelGrid from "./ModelGrid";
import { Model } from "../../api/client";

const mk = (id: number, name: string): Model =>
  ({ id, name, title: name, creator_id: 1, variant_count: 1, thumbnail_path: null, thumbnail_url: null } as unknown as Model);

const models = [mk(1, "Alpha"), mk(2, "Beta")];

const base: React.ComponentProps<typeof ModelGrid> = {
  loading: false,
  isError: false,
  onRetry: vi.fn(),
  onClearFilters: vi.fn(),
  onScanLibrary: vi.fn(),
  models,
  selection: new Set<number>(),
  onSelect: vi.fn(),
  onMutate: vi.fn(),
  excludedView: false,
  onRemoved: vi.fn(),
  guideModelIds: new Set<number>(),
  allTagSuggestions: [],
  focusedIndex: -1,
  gridRef: { current: null },
  dndEnabled: false,
  dndSensors: [],
  dndAnnouncements: {
    onDragStart: () => undefined, onDragOver: () => undefined,
    onDragEnd: () => undefined, onDragCancel: () => undefined,
  },
  onDragStart: vi.fn(),
  onDragEnd: vi.fn(),
  onDragCancel: vi.fn(),
  draggingModel: null,
  dragCount: 0,
};

const renderGrid = (over: Partial<React.ComponentProps<typeof ModelGrid>> = {}) =>
  render(<ModelGrid {...base} {...over} />);

describe("ModelGrid", () => {
  it("shows skeleton placeholders while loading", () => {
    const { container } = renderGrid({ loading: true });
    expect(container.querySelectorAll(".stl-shimmer-overlay").length).toBe(10);
    expect(screen.queryByTestId("model-card")).not.toBeInTheDocument();
  });

  it("shows the empty state when there are no models", () => {
    renderGrid({ models: [] });
    expect(screen.getByText("No models found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Scan library/ })).toBeInTheDocument();
  });

  it("shows the error state when isError is true", () => {
    renderGrid({ isError: true });
    expect(screen.getByText("Couldn't load your library")).toBeInTheDocument();
  });

  it("renders one card per model without DnD when disabled", () => {
    renderGrid({ dndEnabled: false });
    expect(screen.getAllByTestId("model-card")).toHaveLength(2);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("renders cards with drag grips when DnD is enabled", () => {
    renderGrid({ dndEnabled: true });
    expect(screen.getAllByTestId("model-card")).toHaveLength(2);
    // each DraggableCard adds a drag-handle button
    expect(screen.getAllByRole("button", { name: /Drag to group/ })).toHaveLength(2);
  });
});
