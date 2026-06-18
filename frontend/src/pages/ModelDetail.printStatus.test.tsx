import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const get = vi.fn();
const setPrintStatus = vi.fn();
const toastMock = vi.fn();

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
      setPrintStatus: (...a: unknown[]) => setPrintStatus(...a),
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
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("../components/FindOnWeb", () => ({ default: () => null }));
vi.mock("../components/STLViewer", () => ({ default: () => null }));
vi.mock("../components/ImagePicker", () => ({ default: () => null }));
vi.mock("../components/MetadataEditor", () => ({ default: () => null }));
vi.mock("../components/KitBuilder", () => ({ default: () => null }));
vi.mock("../components/StarRating", () => ({ default: () => null }));

import ModelDetail from "./ModelDetail";

const printedModel = {
  id: 1,
  name: "Goblin",
  title: "Goblin",
  nsfw: false,
  is_favorite: false,
  user_rating: null,
  print_status: "printed",
  print_count: 2,
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
};

const renderAt = () =>
  render(
    <MemoryRouter initialEntries={["/models/1"]}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>
  );

describe("ModelDetail clear print status (#379)", () => {
  beforeEach(() => {
    get.mockReset();
    setPrintStatus.mockReset();
    toastMock.mockReset();
  });

  it("clears the status to none and hides the clear control", async () => {
    get.mockResolvedValue(printedModel);
    setPrintStatus.mockResolvedValue({ ok: true, print_status: "none", print_count: 0 });
    renderAt();
    // Wait for the load effect to apply the model's "printed" status, which is
    // what renders the clear control (findByRole retries until it appears).
    const clear = await screen.findByRole("button", { name: "Clear print status" });
    fireEvent.click(clear);

    await waitFor(() => expect(setPrintStatus).toHaveBeenCalledWith(1, "none"));
    // Reverted to 'none' → the clear control is gone and the button reads "Set status".
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Clear print status" })).not.toBeInTheDocument()
    );
    expect(screen.getByText("Set status")).toBeInTheDocument();
  });

  it("has no clear control when status is already none", async () => {
    get.mockResolvedValue({ ...printedModel, print_status: "none", print_count: 0 });
    renderAt();
    await waitFor(() => expect(screen.getByText("Goblin")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: "Clear print status" })).not.toBeInTheDocument();
  });
});
