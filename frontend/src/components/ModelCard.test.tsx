import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ModelCard from "./ModelCard";
import { Model } from "../api/client";

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("./QuickAssignPopover", () => ({
  default: ({ onClose, onRename }: { onClose: () => void; onRename?: () => void }) => (
    <div data-testid="quick-assign-popover">
      <button onClick={onClose}>close-popover</button>
      {onRename && <button onClick={() => { onClose(); onRename(); }}>popover-rename</button>}
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
        setNSFW: vi.fn(async () => ({ ok: true })),
        setExcluded: vi.fn(async () => ({ ok: true, excluded: false })),
        update: vi.fn(async () => ({})),
        variants: vi.fn(async () => ({ items: [{ id: 1 }, { id: 2 }], total: 2 })),
        patchGroup: vi.fn(async () => ({ id: 42, creator_id: 1, label: "Oni", rep_model_id: null, source: "auto", reason: null, confidence: null })),
      },
    },
  };
});

import { api } from "../api/client";

const MODEL = {
  id: 7, name: "robocop", title: "RoboCop", character: null, variant_count: 1,
  nsfw: false, is_favorite: false, needs_review: false,
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

describe("ModelCard parsed-attribute badges (#609)", () => {
  it("renders a support-status badge with a readable label", () => {
    renderCard({ parsed_attributes: { support_status: "unsupported" } });
    expect(screen.getByText("Unsupported")).toBeInTheDocument();
    expect(screen.getByTitle("Print-support status")).toBeInTheDocument();
  });

  it("renders cut/slicer/version chips", () => {
    renderCard({ parsed_attributes: { cut_status: "hollow", slicer: "chitubox", version: "v2" } });
    expect(screen.getByText("hollow")).toBeInTheDocument();
    expect(screen.getByText("chitubox")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
  });

  it("shows no attribute chips when parsed_attributes is empty", () => {
    renderCard({ parsed_attributes: {} });
    expect(screen.queryByTitle("Print-support status")).toBeNull();
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

describe("api.fileUrl content versioning (#185)", () => {
  it("omits the version param when none is given", () => {
    expect(api.fileUrl("/data/thumbnails/7.png")).toBe(
      "/api/files/image?path=%2Fdata%2Fthumbnails%2F7.png"
    );
  });

  it("appends an encoded v= when a version is given", () => {
    expect(api.fileUrl("/data/thumbnails/7.png", "2026-06-15T00:00:00")).toBe(
      "/api/files/image?path=%2Fdata%2Fthumbnails%2F7.png&v=2026-06-15T00%3A00%3A00"
    );
  });
});

describe("ModelCard thumbnail cache-busting (#185)", () => {
  it("versions the thumbnail URL with the model's updated_at", () => {
    renderCard({
      thumbnail_path: "/data/thumbnails/7.png",
      updated_at: "2026-06-15T12:00:00",
    });
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute(
      "src",
      "/api/files/image?path=%2Fdata%2Fthumbnails%2F7.png&v=2026-06-15T12%3A00%3A00"
    );
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
    renderCard({ print_status: "queued" });
    const btn = screen.getByRole("button", { name: /print status queued/i });
    expect(btn.className).toMatch(/sky/);
  });

  it("calls setPrintStatus with next cycle value on click", async () => {
    renderCard({ print_status: "none" });
    const btn = screen.getByRole("button", { name: /print status none/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(vi.mocked(api.models.setPrintStatus)).toHaveBeenCalledWith(7, "queued")
    );
  });
});

describe("ModelCard inline rename (#191)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renames the model on double-click + Enter", async () => {
    renderCard();
    fireEvent.doubleClick(screen.getByText("RoboCop"));
    const input = screen.getByLabelText("Rename model") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "RoboCop 2" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(vi.mocked(api.models.update)).toHaveBeenCalledWith(7, { title: "RoboCop 2" })
    );
    expect(screen.getByText("RoboCop 2")).toBeInTheDocument();
  });

  it("cancels on Escape without saving", () => {
    renderCard();
    fireEvent.doubleClick(screen.getByText("RoboCop"));
    const input = screen.getByLabelText("Rename model") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Nope" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(vi.mocked(api.models.update)).not.toHaveBeenCalled();
    expect(screen.getByText("RoboCop")).toBeInTheDocument();
  });

  it("renames a whole variant group on double-click + Enter", async () => {
    renderCard({ variant_count: 3, character: "Akuma", title: null, variant_group_id: 42 });
    fireEvent.doubleClick(screen.getByText("Akuma"));
    const input = screen.getByLabelText("Rename group") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Oni" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // Relabels the durable VariantGroup row directly — every member follows.
    await waitFor(() =>
      expect(vi.mocked(api.models.patchGroup)).toHaveBeenCalledWith(42, { label: "Oni" })
    );
    expect(screen.getByText("Oni")).toBeInTheDocument();
  });

  it("refuses to rename a group with no durable group id and reverts the input", async () => {
    renderCard({ variant_count: 3, character: "Akuma", title: null, variant_group_id: null });
    fireEvent.doubleClick(screen.getByText("Akuma"));
    const input = screen.getByLabelText("Rename group") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Oni" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByText("Akuma")).toBeInTheDocument());
    expect(vi.mocked(api.models.patchGroup)).not.toHaveBeenCalled();
  });

  it("shows enriched title instead of character slug for an enriched group", () => {
    renderCard({ variant_count: 3, character: "1.Firestar-Regular-stls", title: "Firestar 3D printing model" });
    expect(screen.getByText("Firestar 3D printing model")).toBeInTheDocument();
    expect(screen.queryByText("1.Firestar-Regular-stls")).not.toBeInTheDocument();
  });

  it("falls back to character when group has no title", () => {
    renderCard({ variant_count: 3, character: "Akuma", title: null });
    expect(screen.getByText("Akuma")).toBeInTheDocument();
  });

  it("opens the rename editor from the quick-assign popover", () => {
    renderCard();
    fireEvent.click(screen.getByLabelText("Quick assign tags and collections"));
    fireEvent.click(screen.getByText("popover-rename"));
    expect(screen.getByLabelText("Rename model")).toBeInTheDocument();
  });

  it("marks the card link non-draggable so text selection in rename doesn't drag the URL", () => {
    renderCard();
    // The card is an <a>; native anchor drag would paste the link URL into the
    // rename input when selecting text. draggable={false} prevents that.
    expect(screen.getByRole("link")).toHaveAttribute("draggable", "false");
  });
});

describe("ModelCard inline star rating (#167)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("reflects the model's user_rating", () => {
    renderCard({ user_rating: 3 });
    expect(screen.getByRole("radio", { name: "3 stars" })).toHaveAttribute("aria-checked", "true");
  });

  it("calls setRating when a star is clicked", async () => {
    renderCard({ user_rating: null });
    fireEvent.click(screen.getByRole("radio", { name: "4 stars" }));
    await waitFor(() => expect(vi.mocked(api.models.setRating)).toHaveBeenCalledWith(7, 4));
  });

  it("clears the rating when the active star is clicked again", async () => {
    renderCard({ user_rating: 2 });
    fireEvent.click(screen.getByRole("radio", { name: "2 stars" }));
    await waitFor(() => expect(vi.mocked(api.models.setRating)).toHaveBeenCalledWith(7, null));
  });
});
