/**
 * Tests for deleting an "Other Files" entry on ModelDetail (#880).
 * A stale entry (e.g. the file was removed outside the app) must still be
 * deletable from the listing — the delete call always fires; the backend
 * handles a missing-on-disk file gracefully.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const getMock = vi.fn();
const deleteOtherFileMock = vi.fn(async (..._a: unknown[]) => ({ ok: true }));
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
      variants: vi.fn(async () => ({ items: [] })),
      neighbors: vi.fn(async () => ({ prev: null, next: null })),
      characters: vi.fn(async () => []),
      tags: vi.fn(async () => []),
      deleteOtherFile: (...a: unknown[]) => deleteOtherFileMock(...a),
    },
    painting: { guides: { list: vi.fn(async () => ({ items: [] })) } },
    collections: { list: vi.fn(async () => []) },
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
    documentUrl: (p: string) => p,
  },
}));

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: {
      painting_guides_enabled: false,
      horizontal_parts_layout: false,
      part_categories_enabled: false,
      ai_organize_enabled: false,
    },
  }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => confirmMock }));
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
  other_files: ["/lib/dragonborn/datapackage.json"],
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

describe("ModelDetail — delete Other Files entry (#880)", () => {
  beforeEach(() => {
    getMock.mockReset();
    deleteOtherFileMock.mockClear();
    confirmMock.mockReset();
    confirmMock.mockResolvedValue(true);
  });

  it("shows a delete button for each other-files entry", async () => {
    getMock.mockResolvedValue(baseModel);
    renderDetail();

    expect(await screen.findByText("datapackage.json")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete datapackage\.json/i })).toBeInTheDocument();
  });

  it("asks for confirmation before deleting, and calls the API when confirmed", async () => {
    getMock.mockResolvedValue(baseModel);
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("button", { name: /delete datapackage\.json/i }));

    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({ destructive: true, confirmLabel: "Delete" }),
    );
    await waitFor(() =>
      expect(deleteOtherFileMock).toHaveBeenCalledWith(5, "/lib/dragonborn/datapackage.json"),
    );
  });

  it("does not call the API when the user cancels the confirmation", async () => {
    getMock.mockResolvedValue(baseModel);
    confirmMock.mockResolvedValue(false);
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("button", { name: /delete datapackage\.json/i }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(deleteOtherFileMock).not.toHaveBeenCalled();
  });
});
