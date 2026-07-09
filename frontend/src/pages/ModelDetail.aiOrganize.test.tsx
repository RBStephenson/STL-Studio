/**
 * Tests for the AI Organize strategy picker on ModelDetail (#878).
 * Clicking "AI Organize" must open a strategy-choice modal first — the
 * actual /ai-organize call only fires once the user picks unit vs parts.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";

const getMock = vi.fn();
const aiOrganizeMock = vi.fn(async (..._a: unknown[]) => ({
  suggestions: [], llm_status: "disabled", llm_detail: "no api configured",
}));

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
      aiOrganize: (...a: unknown[]) => aiOrganizeMock(...a),
    },
    painting: { guides: { list: vi.fn(async () => ({ items: [] })) } },
    collections: { list: vi.fn(async () => []) },
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
  },
}));

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    settings: {
      painting_guides_enabled: false,
      horizontal_parts_layout: false,
      part_categories_enabled: false,
      ai_organize_enabled: true,
    },
  }),
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
  stl_files: [
    { id: 1, filename: "widget.stl", path: "/widget.stl", size_bytes: 1024, sup_of_id: null, part_type: null, part_name: null },
  ],
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

describe("ModelDetail AI Organize strategy picker (#878)", () => {
  beforeEach(() => {
    getMock.mockReset();
    aiOrganizeMock.mockClear();
  });

  it("opens the strategy modal instead of calling the API directly", async () => {
    getMock.mockResolvedValue(baseModel);
    const user = userEvent.setup();
    renderDetail();

    const btn = await screen.findByRole("button", { name: /^ai organize$/i });
    await user.click(btn);

    expect(await screen.findByText(/how should the ai categorize/i)).toBeInTheDocument();
    expect(aiOrganizeMock).not.toHaveBeenCalled();
  });

  it("calls the API with strategy='unit' when Unit-based is chosen", async () => {
    getMock.mockResolvedValue(baseModel);
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("button", { name: /^ai organize$/i }));
    await user.click(await screen.findByRole("button", { name: /unit-based/i }));

    await waitFor(() => expect(aiOrganizeMock).toHaveBeenCalledWith(5, "unit"));
  });

  it("calls the API with strategy='parts' when Parts-based is chosen", async () => {
    getMock.mockResolvedValue(baseModel);
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("button", { name: /^ai organize$/i }));
    await user.click(await screen.findByRole("button", { name: /parts-based/i }));

    await waitFor(() => expect(aiOrganizeMock).toHaveBeenCalledWith(5, "parts"));
  });
});
