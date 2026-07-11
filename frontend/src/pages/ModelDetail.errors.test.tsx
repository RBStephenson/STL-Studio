import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const get = vi.fn();
const update = vi.fn();
const updateSTLFile = vi.fn();
const toastMock = vi.fn();

// ApiError is defined inside the (hoisted) mock factory so `instanceof` checks
// in load() match; the test body imports it back from the mocked module.
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
      get: (...a: unknown[]) => get(...a),
      update: (...a: unknown[]) => update(...a),
      updateSTLFile: (...a: unknown[]) => updateSTLFile(...a),
      variants: vi.fn(async () => ({ items: [] })),
      neighbors: vi.fn(async () => ({ prev_id: null, next_id: null })),
      characters: vi.fn(async () => []),
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
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("../components/FindOnWeb", () => ({ default: () => null }));
vi.mock("../components/STLViewer", () => ({ default: () => null }));
vi.mock("../components/ImagePicker", () => ({ default: () => null }));
vi.mock("../components/MetadataEditor", () => ({ default: () => null }));
vi.mock("../components/KitBuilder", () => ({ default: () => null }));
vi.mock("../components/StarRating", () => ({ default: () => null }));

import ModelDetail from "./ModelDetail";
import { QueryWrapper } from "../test/queryWrapper";
import { ApiError } from "../api/client";

const baseModel = {
  id: 1,
  name: "Goblin",
  title: "Goblin",
  nsfw: false,
  is_favorite: false,
  user_rating: null,
  print_status: "none",
  print_count: 0,
  tags: [],
  removed_auto_tags: [],
  auto_tags: ["dragon"],
  collection_ids: [],
  stl_files: [{ id: 10, filename: "part.stl", path: "part.stl", part_type: null, size_bytes: null }],
  image_paths: [],
  thumbnail_path: null,
  thumbnail_url: null,
  creator_id: null,
  character: null,
  has_group_override: false,
};

const renderAt = () =>
  render(
    <QueryWrapper>
    <MemoryRouter initialEntries={["/models/1"]}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>
    </QueryWrapper>
  );

describe("ModelDetail error handling (#221)", () => {
  beforeEach(() => {
    get.mockReset();
    update.mockReset();
    updateSTLFile.mockReset();
    toastMock.mockReset();
  });

  it("shows 'Model not found' on a 404", async () => {
    get.mockRejectedValue(new ApiError(404, "Not Found"));
    renderAt();
    await waitFor(() => expect(screen.getByText("Model not found")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Back to Library" })).toBeInTheDocument();
  });

  it("shows the shared error state (not 'not found') on a network/5xx failure", async () => {
    get.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderAt();
    await waitFor(() => expect(screen.getByText("Retry")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Couldn't load this model")).toBeInTheDocument();
    expect(screen.queryByText("Model not found")).not.toBeInTheDocument();

    // Retry refetches and renders the model.
    get.mockResolvedValueOnce(baseModel);
    fireEvent.click(screen.getByText("Retry"));
    await waitFor(() => expect(screen.getByText("Goblin")).toBeInTheDocument());
  });

  it("reverts the optimistic tag and toasts when addTag fails", async () => {
    get.mockResolvedValue(baseModel);
    update.mockRejectedValue(new ApiError(500, "boom"));
    renderAt();
    await waitFor(() => expect(screen.getByText("Goblin")).toBeInTheDocument());

    // The auto-tag "dragon" exposes an "Add as user tag" button.
    fireEvent.click(screen.getByTitle("Add as user tag"));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith("Couldn't add tag — try again.", "error"));
    // Reverted: the add button is enabled again (tag not promoted).
    expect(screen.getByTitle("Add as user tag")).toBeEnabled();
  });

  it("reverts the optimistic part-type label and toasts when savePartType fails", async () => {
    get.mockResolvedValue(baseModel);
    updateSTLFile.mockRejectedValue(new ApiError(500, "boom"));
    renderAt();
    await waitFor(() => expect(screen.getByText("Goblin")).toBeInTheDocument());

    const input = screen.getByPlaceholderText("Category…") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "head" } });
    fireEvent.blur(input);

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith("Couldn't save category — try again.", "error"));
    await waitFor(() => expect(input.value).toBe(""));
  });
});
