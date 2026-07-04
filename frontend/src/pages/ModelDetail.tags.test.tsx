/**
 * Tests for inline user-tag editing on ModelDetail display mode (#411).
 * Verifies add and remove persist via api.models.update without entering the
 * full edit screen.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const getMock = vi.fn();
const updateMock = vi.fn(async (..._a: unknown[]) => ({}));
const tagsMock = vi.fn(async (..._a: unknown[]) => [{ tag: "hero", count: 3 }]);

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
      update: (...a: unknown[]) => updateMock(...a),
      updateSTLFile: vi.fn(async () => ({})),
      variants: vi.fn(async () => ({ items: [] })),
      neighbors: vi.fn(async () => ({ prev: null, next: null })),
      characters: vi.fn(async () => []),
      tags: (...a: unknown[]) => tagsMock(...a),
    },
    painting: { guides: { list: vi.fn(async () => ({ items: [] })) } },
    collections: { list: vi.fn(async () => []) },
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
  },
}));

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: { painting_guides_enabled: false } }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("../components/FindOnWeb", () => ({ default: () => null }));
vi.mock("../components/STLViewer", () => ({ default: () => null }));
vi.mock("../components/ImagePicker", () => ({ default: () => null }));
vi.mock("../components/MetadataEditor", () => ({ default: () => null }));
vi.mock("../components/KitBuilder", () => ({ default: () => null }));
vi.mock("../components/StarRating", () => ({ default: () => null }));

import ModelDetail from "./ModelDetail";
import { QueryWrapper } from "../test/queryWrapper";

const baseModel = {
  id: 5,
  name: "Dragonborn",
  title: "Dragonborn",
  nsfw: false,
  is_favorite: false,
  user_rating: null,
  print_status: "none",
  print_count: 0,
  tags: [] as string[],
  removed_auto_tags: [] as string[],
  auto_tags: [] as string[],
  collection_ids: [],
  stl_files: [],
  image_paths: [],
  thumbnail_path: null,
  thumbnail_url: null,
  creator_id: null,
  character: null,
  has_group_override: false,
};

function renderDetail() {
  return render(
    <QueryWrapper>
    <MemoryRouter initialEntries={[{ pathname: "/models/5" }]}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>
    </QueryWrapper>,
  );
}

describe("ModelDetail inline tag editing (#411)", () => {
  beforeEach(() => {
    getMock.mockReset();
    updateMock.mockClear();
    tagsMock.mockClear();
  });

  it("adds a tag inline and persists via update", async () => {
    getMock.mockResolvedValue({ ...baseModel, tags: [] });
    const user = userEvent.setup();
    renderDetail();

    const addBtn = await screen.findByRole("button", { name: /add tag/i });
    await user.click(addBtn);

    const input = await screen.findByPlaceholderText(/add tag/i);
    await user.type(input, "knight{Enter}");

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(5, { tags: ["knight"] }),
    );
  });

  it("removes an existing user tag inline and persists via update", async () => {
    getMock.mockResolvedValue({ ...baseModel, tags: ["knight", "hero"] });
    const user = userEvent.setup();
    renderDetail();

    // Enter the inline editor.
    const editBtn = await screen.findByRole("button", { name: /edit tags/i });
    await user.click(editBtn);

    // TagInput renders an X button per tag; remove "knight".
    const tagChip = (await screen.findByText("knight")).closest("span")!;
    const removeBtn = tagChip.querySelector("button")!;
    await user.click(removeBtn);

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(5, { tags: ["hero"] }),
    );
  });
});
