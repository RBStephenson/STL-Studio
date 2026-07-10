import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Triage from "./Triage";

const MODEL = vi.hoisted(() => ({
  id: 1, name: "widget.stl", title: "Widget", folder_path: "/lib/widget",
  thumbnail_path: null, thumbnail_url: null, creator_id: null,
  auto_tags: [], removed_auto_tags: [], tags: [], needs_review: true,
}));

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      ...orig.api,
      fileUrl: (p: string) => p,
      models: {
        list: vi.fn().mockResolvedValue({ items: [MODEL] }),
        stats: vi.fn().mockResolvedValue({ needs_review: 1, queued: 0 }),
        creators: vi.fn().mockResolvedValue([]),
        update: vi.fn().mockResolvedValue({ ...MODEL, needs_review: false }),
      },
    },
  };
});

function renderPage() {
  return render(<MemoryRouter><Triage /></MemoryRouter>);
}

describe("Triage keyboard-hint row", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows a styled kbd hint row for dismiss/skip/back bound to the real handlers", async () => {
    renderPage();
    await screen.findByText("Widget");

    expect(screen.getByText("→ / Space")).toBeInTheDocument();
    expect(screen.getByText("dismiss (looks fine)")).toBeInTheDocument();
    expect(screen.getByText("skip")).toBeInTheDocument();
    expect(screen.getByText("back")).toBeInTheDocument();

    const kbd = screen.getByText("→ / Space").closest("kbd");
    expect(kbd?.tagName).toBe("KBD");
    expect(kbd).toHaveStyle({ background: "#1c1e26", color: "#dcdde2" });
  });

  it("dismisses the current model on Space, matching the → / Space hint", async () => {
    const { api } = await import("../api/client");
    renderPage();
    await screen.findByText("Widget");

    await userEvent.keyboard(" ");
    expect(api.models.update).toHaveBeenCalledWith(1, { needs_review: false });
  });
});
