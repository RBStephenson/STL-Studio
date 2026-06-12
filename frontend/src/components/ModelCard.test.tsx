import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ModelCard from "./ModelCard";
import { Model } from "../api/client";

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("./QuickAssignPopover", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="quick-assign-popover">
      <button onClick={onClose}>close-popover</button>
    </div>
  ),
}));

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
        setRating: vi.fn(async () => ({ ok: true, user_rating: 4 })),
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

describe("ModelCard quick-assign button (#172)", () => {
  it("shows the quick-assign button with aria-label", () => {
    render(<MemoryRouter><ModelCard model={MODEL} /></MemoryRouter>);
    expect(screen.getByLabelText("Quick assign tags and collections")).toBeInTheDocument();
  });

  it("opens the QuickAssignPopover when the button is clicked", () => {
    render(<MemoryRouter><ModelCard model={MODEL} /></MemoryRouter>);
    expect(screen.queryByTestId("quick-assign-popover")).toBeNull();
    fireEvent.click(screen.getByLabelText("Quick assign tags and collections"));
    expect(screen.getByTestId("quick-assign-popover")).toBeInTheDocument();
  });

  it("closes the popover when onClose is called", () => {
    render(<MemoryRouter><ModelCard model={MODEL} /></MemoryRouter>);
    fireEvent.click(screen.getByLabelText("Quick assign tags and collections"));
    expect(screen.getByTestId("quick-assign-popover")).toBeInTheDocument();
    fireEvent.click(screen.getByText("close-popover"));
    expect(screen.queryByTestId("quick-assign-popover")).toBeNull();
  });
});

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

describe("ModelCard inline star rating (#167)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("reflects the model's user_rating", () => {
    renderCard({ user_rating: 3 } as any);
    expect(screen.getByRole("radio", { name: "3 stars" })).toHaveAttribute("aria-checked", "true");
  });

  it("calls setRating when a star is clicked", async () => {
    renderCard({ user_rating: null } as any);
    fireEvent.click(screen.getByRole("radio", { name: "4 stars" }));
    await waitFor(() => expect(vi.mocked(api.models.setRating)).toHaveBeenCalledWith(7, 4));
  });

  it("clears the rating when the active star is clicked again", async () => {
    renderCard({ user_rating: 2 } as any);
    fireEvent.click(screen.getByRole("radio", { name: "2 stars" }));
    await waitFor(() => expect(vi.mocked(api.models.setRating)).toHaveBeenCalledWith(7, null));
  });
});
