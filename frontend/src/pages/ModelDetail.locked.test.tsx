/**
 * #978: the model detail page header needs its own Lock toggle, mirroring
 * the one on the Library card — it was initially added only to ModelCard.tsx,
 * leaving no way to lock/unlock from the detail page itself.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const getMock = vi.fn();
const setLockedMock = vi.fn(async (..._args: unknown[]) => ({ ok: true, locked: true }));

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
      setLocked: (...a: unknown[]) => setLockedMock(...a),
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

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: false }) }));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: { painting_guides_enabled: false, part_categories_enabled: true }, update: vi.fn() }),
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
  id: 1,
  name: "Hero A",
  title: "Hero A",
  nsfw: false,
  is_favorite: false,
  locked: false,
  user_rating: null,
  print_status: "none",
  print_count: 0,
  tags: [],
  removed_auto_tags: [],
  auto_tags: [],
  collection_ids: [],
  stl_files: [],
  image_paths: [],
  thumbnail_path: "/hero-a.jpg",
  thumbnail_url: null,
  creator_id: 3,
  character: "Hero",
  variant_group_id: null,
  variant_group: null,
};

function renderDetail() {
  return render(
    <QueryWrapper>
    <MemoryRouter initialEntries={[{ pathname: "/models/1" }]}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>
    </QueryWrapper>,
  );
}

describe("ModelDetail Lock toggle (#978)", () => {
  beforeEach(() => {
    getMock.mockReset();
    setLockedMock.mockClear();
  });

  it("shows the unlocked title and calls setLocked(true) when clicked", async () => {
    getMock.mockResolvedValue({ ...baseModel, locked: false });
    renderDetail();
    await waitFor(() => expect(screen.getByTitle("Lock: block file, category, and part-name changes")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Lock: block file, category, and part-name changes"));
    await waitFor(() => expect(setLockedMock).toHaveBeenCalledWith(1, true));
  });

  it("shows the locked title and calls setLocked(false) when clicked", async () => {
    getMock.mockResolvedValue({ ...baseModel, locked: true });
    renderDetail();
    await waitFor(() => expect(screen.getByTitle("Locked — unlock to allow file/category/name changes")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Locked — unlock to allow file/category/name changes"));
    await waitFor(() => expect(setLockedMock).toHaveBeenCalledWith(1, false));
  });
});
