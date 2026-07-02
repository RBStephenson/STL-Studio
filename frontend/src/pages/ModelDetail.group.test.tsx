/**
 * Tests for ModelDetail's durable-group actions (#678 Phase 4): merging a
 * model into an existing VariantGroup and removing it from its current one.
 * Replaces the legacy GroupOverride set/clear flow (setGroupOverride /
 * clearGroupOverride), which is gone from this page.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const getMock = vi.fn();
const variantsMock = vi.fn();
const mergeGroupMock = vi.fn();
const splitGroupMock = vi.fn();
const toastMock = vi.fn();
const confirmMock = vi.fn(async () => true);

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
  api: {
    models: {
      get: (...a: unknown[]) => getMock(...a),
      update: vi.fn(async () => ({})),
      updateSTLFile: vi.fn(async () => ({})),
      variants: (...a: unknown[]) => variantsMock(...a),
      mergeGroup: (...a: unknown[]) => mergeGroupMock(...a),
      splitGroup: (...a: unknown[]) => splitGroupMock(...a),
      neighbors: vi.fn(async () => ({ prev_id: null, next_id: null })),
      characters: vi.fn(async () => ["Rocky", "Apollo"]),
    },
    painting: { guides: { list: vi.fn(async () => ({ items: [] })) } },
    collections: { list: vi.fn(async () => []) },
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
  },
}));

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: { painting_guides_enabled: false, part_categories_enabled: true }, update: vi.fn() }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => confirmMock }));
vi.mock("../components/FindOnWeb", () => ({ default: () => null }));
vi.mock("../components/STLViewer", () => ({ default: () => null }));
vi.mock("../components/ImagePicker", () => ({ default: () => null }));
vi.mock("../components/MetadataEditor", () => ({ default: () => null }));
vi.mock("../components/KitBuilder", () => ({ default: () => null }));
vi.mock("../components/StarRating", () => ({ default: () => null }));

import ModelDetail from "./ModelDetail";

const baseModel = {
  id: 1,
  name: "Rocky Bust",
  title: "Rocky Bust",
  nsfw: false,
  is_favorite: false,
  user_rating: null,
  print_status: "none",
  print_count: 0,
  tags: [],
  removed_auto_tags: [],
  auto_tags: [],
  collection_ids: [],
  stl_files: [],
  image_paths: [],
  thumbnail_path: null,
  thumbnail_url: null,
  creator_id: 3,
  character: "Rocky",
  variant_group_id: null,
  variant_group: null,
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/models/1" }]}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ModelDetail durable group actions (#678)", () => {
  beforeEach(() => {
    getMock.mockReset();
    variantsMock.mockReset();
    mergeGroupMock.mockReset();
    splitGroupMock.mockReset();
    toastMock.mockReset();
    confirmMock.mockClear();
    variantsMock.mockResolvedValue({ items: [] });
  });

  it("shows 'Merge into group' for an ungrouped model, not 'Group:'", async () => {
    getMock.mockResolvedValue({ ...baseModel, variant_group_id: null, variant_group: null });
    renderDetail();
    expect(await screen.findByText("Merge into group")).toBeInTheDocument();
    expect(screen.queryByText(/^Group:/)).not.toBeInTheDocument();
  });

  it("shows 'Group: <label>' and a remove control for a grouped model", async () => {
    getMock.mockResolvedValue({
      ...baseModel,
      variant_group_id: 7,
      variant_group: { id: 7, creator_id: 3, label: "Rocky Franchise", rep_model_id: 1, source: "manual", reason: null, confidence: null },
    });
    renderDetail();
    expect(await screen.findByText("Group: Rocky Franchise")).toBeInTheDocument();
    expect(screen.getByTitle("Remove this model from its group")).toBeInTheDocument();
  });

  it("merges into an existing group resolved from the typed name", async () => {
    getMock.mockResolvedValue({ ...baseModel, variant_group_id: null, variant_group: null });
    variantsMock.mockResolvedValue({
      items: [{ id: 20, variant_group_id: 7, variant_group: { label: "Apollo Creed" } }],
    });
    mergeGroupMock.mockResolvedValue({ id: 7, creator_id: 3, label: "Apollo Creed", rep_model_id: 20, source: "manual", reason: null, confidence: null });
    renderDetail();

    fireEvent.click(await screen.findByText("Merge into group"));
    const input = await screen.findByPlaceholderText("Existing group name…");
    fireEvent.change(input, { target: { value: "Apollo" } });
    await waitFor(() => expect(screen.getByText("Merge")).not.toBeDisabled());
    fireEvent.click(screen.getByText("Merge"));

    await waitFor(() =>
      expect(mergeGroupMock).toHaveBeenCalledWith([1], { groupId: 7, label: "Apollo Creed" }),
    );
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("Merged into"), "success");
  });

  it("refuses to merge into a name that doesn't resolve to an existing group", async () => {
    getMock.mockResolvedValue({ ...baseModel, variant_group_id: null, variant_group: null });
    variantsMock.mockResolvedValue({ items: [] }); // no existing member under that name
    renderDetail();

    fireEvent.click(await screen.findByText("Merge into group"));
    const input = await screen.findByPlaceholderText("Existing group name…");
    fireEvent.change(input, { target: { value: "Brand New Group" } });
    fireEvent.click(screen.getByText("Merge"));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("No existing group named"), "error"),
    );
    expect(mergeGroupMock).not.toHaveBeenCalled();
  });

  it("removes the model from its group after confirming", async () => {
    getMock.mockResolvedValue({
      ...baseModel,
      variant_group_id: 7,
      variant_group: { id: 7, creator_id: 3, label: "Rocky Franchise", rep_model_id: 1, source: "manual", reason: null, confidence: null },
    });
    splitGroupMock.mockResolvedValue({ ok: true, removed: [1] });
    renderDetail();

    fireEvent.click(await screen.findByTitle("Remove this model from its group"));

    await waitFor(() => expect(splitGroupMock).toHaveBeenCalledWith(7, [1]));
    expect(confirmMock).toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith("Removed from group.", "success");
  });

  it("does nothing when the removal confirm is declined", async () => {
    confirmMock.mockResolvedValueOnce(false);
    getMock.mockResolvedValue({
      ...baseModel,
      variant_group_id: 7,
      variant_group: { id: 7, creator_id: 3, label: "Rocky Franchise", rep_model_id: 1, source: "manual", reason: null, confidence: null },
    });
    renderDetail();

    fireEvent.click(await screen.findByTitle("Remove this model from its group"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(splitGroupMock).not.toHaveBeenCalled();
  });
});
