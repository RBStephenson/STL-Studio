/**
 * STUDIO-45: the small variant-switcher thumbnails on the detail page must
 * blur NSFW variants when "Show NSFW" is off, matching the main image and
 * Library cards.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const getMock = vi.fn();
const variantsMock = vi.fn();
let showNSFW = false;

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
      neighbors: vi.fn(async () => ({ prev_id: null, next_id: null })),
      characters: vi.fn(async () => []),
    },
    painting: { guides: { list: vi.fn(async () => ({ items: [] })) } },
    collections: { list: vi.fn(async () => []) },
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
  },
}));

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW }) }));
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

const baseModel = {
  id: 1,
  name: "Hero A",
  title: "Hero A",
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
  thumbnail_path: "/hero-a.jpg",
  thumbnail_url: null,
  creator_id: 3,
  character: "Hero",
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

describe("ModelDetail variant switcher NSFW blur (STUDIO-45)", () => {
  beforeEach(() => {
    getMock.mockReset();
    variantsMock.mockReset();
    showNSFW = false;
    getMock.mockResolvedValue(baseModel);
    variantsMock.mockResolvedValue({
      items: [
        baseModel,
        { ...baseModel, id: 2, name: "Hero B", title: "Hero B", nsfw: true, thumbnail_path: "/hero-b.jpg" },
      ],
    });
  });

  it("blurs an NSFW variant's thumbnail when showNSFW is off", async () => {
    const { container } = renderDetail();
    await waitFor(() => expect(container.querySelector('img[src="/hero-b.jpg"]')).not.toBeNull());
    const img = container.querySelector('img[src="/hero-b.jpg"]') as HTMLImageElement;
    expect(img.className).toContain("blur-lg");
    expect(img.parentElement?.querySelector("span")?.textContent).toBe("NSFW");
  });

  it("does not blur an SFW variant's thumbnail", async () => {
    const { container } = renderDetail();
    await waitFor(() => expect(container.querySelector('img[src="/hero-a.jpg"]')).not.toBeNull());
    const img = container.querySelector('img[src="/hero-a.jpg"].object-cover') as HTMLImageElement;
    expect(img.className).not.toContain("blur-lg");
  });

  it("clears the blur when showNSFW is on", async () => {
    showNSFW = true;
    const { container } = renderDetail();
    await waitFor(() => expect(container.querySelector('img[src="/hero-b.jpg"]')).not.toBeNull());
    const img = container.querySelector('img[src="/hero-b.jpg"]') as HTMLImageElement;
    expect(img.className).not.toContain("blur-lg");
    expect(img.parentElement?.querySelector("span")).toBeNull();
  });

  it("blurs every variant when the current model itself is NSFW, even SFW-tagged siblings", async () => {
    getMock.mockResolvedValue({ ...baseModel, nsfw: true });
    const { container } = renderDetail();
    await waitFor(() => expect(container.querySelector('img[src="/hero-a.jpg"].object-cover')).not.toBeNull());
    const img = container.querySelector('img[src="/hero-a.jpg"].object-cover') as HTMLImageElement;
    expect(img.className).toContain("blur-lg");
  });
});
