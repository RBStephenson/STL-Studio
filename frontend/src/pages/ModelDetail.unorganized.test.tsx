import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

// STUDIO-405: the unorganized badge is decided by the destination template, but
// it used to be an inert icon whose tooltip said "run Reorganize Library" — advice
// that goes nowhere when that feature's flag is off, which is its default. The
// badge now links to the setting that actually produced it.

const get = vi.fn();

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
  PRINT_STATUS_CYCLE: ["none", "queued", "printing", "printed"],
  api: {
    models: {
      get: (...a: unknown[]) => get(...a),
      update: vi.fn(),
      updateSTLFile: vi.fn(),
      setPrintStatus: vi.fn(),
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

const model = {
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
  auto_tags: [],
  collection_ids: [],
  stl_files: [{ id: 10, filename: "part.stl", path: "part.stl", part_type: null, size_bytes: null }],
  image_paths: [],
  thumbnail_path: null,
  thumbnail_url: null,
  creator_id: null,
  character: null,
  has_group_override: false,
  unorganized: false,
};

const renderAt = () =>
  render(
    <QueryWrapper>
      <MemoryRouter initialEntries={["/models/1"]}>
        <Routes>
          <Route path="/models/:id" element={<ModelDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryWrapper>,
  );

const badge = () => screen.queryByRole("link", { name: /unorganized/i });

describe("ModelDetail unorganized badge (STUDIO-405)", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("links an unorganized model back to the template that decided it", async () => {
    get.mockResolvedValue({ ...model, unorganized: true });
    renderAt();

    const link = await screen.findByRole("link", { name: /unorganized/i });
    expect(link).toHaveAttribute("href", "/settings#library");
  });

  it("shows no badge at all when the model is where the template wants it", async () => {
    get.mockResolvedValue({ ...model, unorganized: false });
    renderAt();
    await waitFor(() => expect(screen.getByText("Goblin")).toBeInTheDocument());

    expect(badge()).toBeNull();
  });

  // The tooltip is the only thing a mouse user sees, and its old text pointed at
  // a tool that is off by default. Pin what it now points at instead.
  it("names the setting rather than telling you to run a disabled tool", async () => {
    get.mockResolvedValue({ ...model, unorganized: true });
    renderAt();

    const link = await screen.findByRole("link", { name: /unorganized/i });
    expect(link).toHaveAttribute("title", expect.stringContaining("Settings → Library"));
    expect(link.getAttribute("title")).not.toMatch(/run reorganize/i);
  });
});
