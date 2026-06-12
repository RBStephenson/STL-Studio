import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ModelCard from "./ModelCard";
import { Model } from "../api/client";

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      models: {
        ...actual.api.models,
        setPrintStatus: vi.fn(async () => ({ ok: true, print_status: "queued", print_count: 0 })),
        setFavorite: vi.fn(async () => ({ ok: true, is_favorite: false })),
        setQueue: vi.fn(async () => ({ ok: true, in_queue: false })),
        setNSFW: vi.fn(async () => ({ ok: true })),
        setExcluded: vi.fn(async () => ({ ok: true, excluded: false })),
      },
    },
  };
});

import { api } from "../api/client";

const MODEL = {
  id: 7, name: "robocop", title: "RoboCop", character: null, variant_count: 1,
  nsfw: false, is_favorite: false, in_queue: false, needs_review: false,
  print_status: "none", print_count: 0,
  auto_tags: [], tags: [], thumbnail_path: null, thumbnail_url: null,
  rating: null, source_site: null, creator_id: 1,
  created_at: "2020-01-01T00:00:00", updated_at: "2020-01-01T00:00:00",
} as unknown as Model;

const renderCard = (model: Partial<Model> = {}) =>
  render(<MemoryRouter><ModelCard model={{ ...MODEL, ...model } as Model} /></MemoryRouter>);

describe("ModelCard painting-guide badge (#263)", () => {
  it("shows the Guide badge when the model has a guide", () => {
    render(<MemoryRouter><ModelCard model={MODEL as Model} hasGuide={true} /></MemoryRouter>);
    expect(screen.getByText("Guide")).toBeInTheDocument();
    expect(screen.getByTitle("Has a painting guide")).toBeInTheDocument();
  });

  it("omits the badge when there is no guide", () => {
    render(<MemoryRouter><ModelCard model={MODEL as Model} hasGuide={false} /></MemoryRouter>);
    expect(screen.queryByText("Guide")).toBeNull();
  });
});

describe("ModelCard print-status cycle (#166)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the print status button with none state initially", () => {
    renderCard();
    const btn = screen.getByRole("button", { name: /print status none/i });
    expect(btn).toBeInTheDocument();
  });

  it("shows queued color when print_status is queued", () => {
    renderCard({ print_status: "queued" } as any);
    const btn = screen.getByRole("button", { name: /print status queued/i });
    expect(btn.className).toMatch(/sky/);
  });

  it("calls setPrintStatus with next cycle value on click", async () => {
    renderCard({ print_status: "none" } as any);
    const btn = screen.getByRole("button", { name: /print status none/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(vi.mocked(api.models.setPrintStatus)).toHaveBeenCalledWith(7, "queued")
    );
  });
});
