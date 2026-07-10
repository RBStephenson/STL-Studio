import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import GuidesPage from "./GuidesPage";

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      painting: {
        guides: {
          list: vi.fn().mockResolvedValue({
            total: 2, page: 1, page_size: 200,
            items: [
              { id: 1, slug: "robocop", title: "RoboCop", category_id: null, series_id: null,
                model_id: null, scale: "1:6", status: "published", franchise: "RoboCop",
                technique_tags: ["TMM"], paint_lines_used: [], updated_at: null, published_at: null },
              { id: 2, slug: "presto", title: "Presto", category_id: null, series_id: null,
                model_id: null, scale: "1:12", status: "draft", franchise: null,
                technique_tags: [], paint_lines_used: [], updated_at: null, published_at: null },
            ],
          }),
        },
      },
    },
  };
});

function renderPage() {
  return render(<MemoryRouter><GuidesPage /></MemoryRouter>);
}

describe("GuidesPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("lists guides as links to the reader, flagging non-published status", async () => {
    renderPage();
    const robo = await screen.findByRole("link", { name: /RoboCop/ });
    expect(robo).toHaveAttribute("href", "/painting/guides/1");
    const presto = screen.getByRole("link", { name: /Presto/ });
    expect(presto).toHaveAttribute("href", "/painting/guides/2");
    expect(screen.getByText("draft")).toBeInTheDocument();           // non-published badge
    expect(screen.queryByText("published")).toBeNull();              // published shows no badge
  });

  it("shows an empty state when there are no guides", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.list).mockResolvedValueOnce({
      total: 0, page: 1, page_size: 200, items: [],
    });
    renderPage();
    expect(await screen.findByText("No painting guides yet")).toBeInTheDocument();
    // Header always has a "New guide" link; the empty-state CTA adds a second.
    const newGuideLinks = screen.getAllByRole("link", { name: /new guide/i });
    expect(newGuideLinks).toHaveLength(2);
    newGuideLinks.forEach((l) => expect(l).toHaveAttribute("href", "/painting/guides/new"));
  });

  it("opens the import modal from the header button (#277)", async () => {
    renderPage();
    await screen.findByRole("link", { name: /RoboCop/ });
    expect(screen.queryByTestId("import-guide-modal")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /import guide/i }));
    expect(screen.getByTestId("import-guide-modal")).toBeInTheDocument();
  });
});
