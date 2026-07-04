/**
 * Tests for ModelDetail Prev/Next navigation and parseLibraryOrigin (#224).
 *
 * parseLibraryOrigin (internal) is verified indirectly:
 *   - via the params passed to api.models.neighbors (the filter context for
 *     the neighbours lookup must match the origin Library URL)
 *   - via whether the Prev/Next controls appear at all (only when the origin
 *     path is exactly "/")
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const neighborsMock = vi.fn();
const getMock = vi.fn();

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
      neighbors: (...a: unknown[]) => neighborsMock(...a),
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
  tags: [],
  removed_auto_tags: [],
  auto_tags: [],
  collection_ids: [],
  stl_files: [],
  image_paths: [],
  thumbnail_path: null,
  thumbnail_url: null,
  creator_id: null,
  character: null,
  has_group_override: false,
};

/** Render ModelDetail for model id=5, optionally with a location.state.from */
function renderDetail(from?: string) {
  return render(
    <QueryWrapper>
    <MemoryRouter
      initialEntries={[{ pathname: "/models/5", state: from ? { from } : undefined }]}
    >
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>
    </QueryWrapper>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  neighborsMock.mockReset();
  getMock.mockResolvedValue(baseModel);
  neighborsMock.mockResolvedValue({ prev_id: null, next_id: null });
});

// ---------------------------------------------------------------------------
// Prev/Next visibility — driven by navOrigin (parseLibraryOrigin)
// ---------------------------------------------------------------------------
describe("ModelDetail Prev/Next visibility (#224)", () => {
  it("hides Prev/Next when navigated to directly (no from state)", async () => {
    renderDetail(undefined);
    await waitFor(() => expect(screen.getByText("Dragonborn")).toBeInTheDocument());
    // neighbors should not even be called when there's no origin
    expect(neighborsMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Prev")).not.toBeInTheDocument();
    expect(screen.queryByText("Next")).not.toBeInTheDocument();
  });

  it("hides Prev/Next when origin is not the Library root (/)", async () => {
    renderDetail("/collections/3");
    await waitFor(() => expect(screen.getByText("Dragonborn")).toBeInTheDocument());
    expect(neighborsMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Prev")).not.toBeInTheDocument();
  });

  it("shows Prev/Next when origin is the Library root", async () => {
    renderDetail("/?q=dragon");
    await waitFor(() => expect(screen.getByText("Dragonborn")).toBeInTheDocument());
    // Controls appear (disabled at boundaries, but present)
    await waitFor(() => expect(screen.getByText("Prev")).toBeInTheDocument());
    expect(screen.getByText("Next")).toBeInTheDocument();
  });

  it("renders Prev as a link when prev_id is returned", async () => {
    neighborsMock.mockResolvedValue({ prev_id: 4, next_id: null });
    renderDetail("/");
    await waitFor(() => expect(screen.getByText("Dragonborn")).toBeInTheDocument());
    await waitFor(() => {
      const prevEl = screen.getByText("Prev").closest("a");
      expect(prevEl).toHaveAttribute("href", "/models/4");
    });
  });

  it("renders Next as a link when next_id is returned", async () => {
    neighborsMock.mockResolvedValue({ prev_id: null, next_id: 6 });
    renderDetail("/");
    await waitFor(() => expect(screen.getByText("Dragonborn")).toBeInTheDocument());
    await waitFor(() => {
      const nextEl = screen.getByText("Next").closest("a");
      expect(nextEl).toHaveAttribute("href", "/models/6");
    });
  });
});

// ---------------------------------------------------------------------------
// parseLibraryOrigin — verified via neighbors call params
// ---------------------------------------------------------------------------
describe("parseLibraryOrigin: neighbors call params (#224)", () => {
  it("passes group_variants=true for a plain Library origin", async () => {
    renderDetail("/");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ group_variants: true }),
    );
  });

  it("passes group_variants=false for a favorites-filtered origin", async () => {
    renderDetail("/?is_favorite=1");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ is_favorite: true, group_variants: false }),
    );
  });

  it("passes group_variants=false for a print_status-filtered origin", async () => {
    renderDetail("/?print_status=printed");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ print_status: "printed", group_variants: false }),
    );
  });

  it("passes group_variants=false for the excluded view", async () => {
    renderDetail("/?excluded=1");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ excluded: true, group_variants: false }),
    );
  });

  it("passes sort param when the Library was sorted non-default", async () => {
    renderDetail("/?sort=added");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ sort: "added", group_variants: true }),
    );
  });

  it("passes added_within_days and sort=added for a recently-added origin", async () => {
    renderDetail("/?added_days=7");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ added_within_days: "7", sort: "added", group_variants: true }),
    );
  });

  it("passes nsfw=false when origin has nsfw=0 (tri-state false)", async () => {
    renderDetail("/?nsfw=0");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ nsfw: false }),
    );
  });

  it("passes text search q param", async () => {
    renderDetail("/?q=dragon&creator_id=3");
    await waitFor(() => expect(neighborsMock).toHaveBeenCalled());
    expect(neighborsMock).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ q: "dragon", creator_id: "3", group_variants: true }),
    );
  });
});
