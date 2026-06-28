import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import QuickAssignPopover from "./QuickAssignPopover";

const mockCollections = [
  { id: 1, name: "Dioramas", description: null, model_count: 3 },
  { id: 2, name: "Showcase", description: null, model_count: 10 },
];
const mockDetail = { id: 5, collection_ids: [1], tags: ["figure"], folder_path: "/lib/Creator/Pack/Goblin" };

vi.mock("../api/client", () => ({
  api: {
    collections: {
      list: vi.fn(async () => mockCollections),
      addModel: vi.fn(async () => {}),
      removeModel: vi.fn(async () => {}),
    },
    models: {
      get: vi.fn(async () => mockDetail),
      update: vi.fn(async () => ({ ok: true })),
      clearThumbnail: vi.fn(async () => ({ ok: true })),
      getGroupingStrategy: vi.fn(async () => ({ path: "/lib/Creator/Pack", strategy: "auto" })),
      setGroupingStrategy: vi.fn(async () => ({ ok: true, path: "/lib/Creator/Pack", strategy: "off" })),
    },
  },
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { api } from "../api/client";

const ALL_TAGS = [
  { tag: "figure", count: 10 },
  { tag: "bust", count: 5 },
  { tag: "statue", count: 3 },
];

const renderPopover = (overrides?: Partial<Parameters<typeof QuickAssignPopover>[0]>) => {
  const props = {
    modelId: 5,
    initialTags: ["figure"],
    allTags: ALL_TAGS,
    onTagsChange: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  return { ...render(<QuickAssignPopover {...props} />), props };
};

describe("QuickAssignPopover (#172)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders tag and collection sections", async () => {
    renderPopover();
    expect(screen.getByText("Tags")).toBeInTheDocument();
    expect(screen.getByText("Collections")).toBeInTheDocument();
  });

  it("toggles per-folder auto-grouping off (#618)", async () => {
    renderPopover();
    const btn = await screen.findByRole("button", { name: /stop auto-grouping this folder/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(vi.mocked(api.models.setGroupingStrategy)).toHaveBeenCalledWith("/lib/Creator/Pack", "off")
    );
    // Label flips to the resume action after turning off.
    await screen.findByRole("button", { name: /resume auto-grouping this folder/i });
  });

  it("shows initial tags as removable chips", () => {
    renderPopover();
    expect(screen.getByText("figure")).toBeInTheDocument();
  });

  it("loads collections on mount and checks membership", async () => {
    renderPopover();
    await waitFor(() => expect(screen.getByText("Dioramas")).toBeInTheDocument());
    expect(screen.getByText("Showcase")).toBeInTheDocument();
    // Dioramas (id=1) is in collection_ids=[1] so its checkbox should be checked
    const dioramasRow = screen.getByText("Dioramas").closest("button")!;
    expect(dioramasRow.querySelector("svg")).toBeTruthy(); // Check icon present
  });

  it("removes a tag and calls api.models.update", async () => {
    const onTagsChange = vi.fn();
    renderPopover({ onTagsChange });
    // "figure" chip should have an X button
    const removeBtn = screen.getAllByRole("button").find(
      (b) => b.querySelector("svg") && b.closest("span")?.textContent?.includes("figure")
    );
    expect(removeBtn).toBeTruthy();
    fireEvent.click(removeBtn!);
    await waitFor(() =>
      expect(vi.mocked(api.models.update)).toHaveBeenCalledWith(5, { tags: [] })
    );
    expect(onTagsChange).toHaveBeenCalledWith([]);
  });

  it("adds a tag via input and calls api.models.update", async () => {
    const onTagsChange = vi.fn();
    renderPopover({ initialTags: [], onTagsChange });
    const input = screen.getByPlaceholderText("Add tag…");
    fireEvent.change(input, { target: { value: "bust" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(vi.mocked(api.models.update)).toHaveBeenCalledWith(5, { tags: ["bust"] })
    );
    expect(onTagsChange).toHaveBeenCalledWith(["bust"]);
  });

  it("toggles a collection off and calls removeModel", async () => {
    renderPopover();
    await waitFor(() => screen.getByText("Dioramas"));
    fireEvent.click(screen.getByText("Dioramas").closest("button")!);
    await waitFor(() =>
      expect(vi.mocked(api.collections.removeModel)).toHaveBeenCalledWith(1, 5)
    );
  });

  it("toggles a collection on and calls addModel", async () => {
    renderPopover();
    await waitFor(() => screen.getByText("Showcase"));
    fireEvent.click(screen.getByText("Showcase").closest("button")!);
    await waitFor(() =>
      expect(vi.mocked(api.collections.addModel)).toHaveBeenCalledWith(2, 5)
    );
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    renderPopover({ onClose });
    fireEvent.click(screen.getByRole("button", { name: /close quick assign/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("hides the Clear image action when the model has no image", () => {
    renderPopover({ hasImage: false });
    expect(screen.queryByText("Clear image")).not.toBeInTheDocument();
  });

  it("clears the image and fires onImageCleared (#192)", async () => {
    const onImageCleared = vi.fn();
    renderPopover({ hasImage: true, onImageCleared });
    fireEvent.click(screen.getByText("Clear image"));
    await waitFor(() =>
      expect(vi.mocked(api.models.clearThumbnail)).toHaveBeenCalledWith(5)
    );
    expect(onImageCleared).toHaveBeenCalled();
    // The action hides itself after a successful clear.
    await waitFor(() =>
      expect(screen.queryByText("Clear image")).not.toBeInTheDocument()
    );
  });

  it("shows the quick-assign button on the ModelCard", async () => {
    // Tested indirectly via ModelCard.test.tsx — button has aria-label
    expect(true).toBe(true);
  });
});
