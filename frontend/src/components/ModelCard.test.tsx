import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ModelCard from "./ModelCard";
import { Model } from "../api/client";

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

const MODEL = {
  id: 7, name: "robocop", title: "RoboCop", character: null, variant_count: 1,
  nsfw: false, is_favorite: false, in_queue: false, needs_review: false,
  auto_tags: [], tags: [], thumbnail_path: null, thumbnail_url: null,
  rating: null, source_site: null, creator_id: 1,
  created_at: "2020-01-01T00:00:00", updated_at: "2020-01-01T00:00:00",
} as unknown as Model;

const renderCard = (hasGuide: boolean) =>
  render(<MemoryRouter><ModelCard model={MODEL} hasGuide={hasGuide} /></MemoryRouter>);

describe("ModelCard painting-guide badge (#263)", () => {
  it("shows the Guide badge when the model has a guide", () => {
    renderCard(true);
    expect(screen.getByText("Guide")).toBeInTheDocument();
    expect(screen.getByTitle("Has a painting guide")).toBeInTheDocument();
  });

  it("omits the badge when there is no guide", () => {
    renderCard(false);
    expect(screen.queryByText("Guide")).toBeNull();
  });
});
