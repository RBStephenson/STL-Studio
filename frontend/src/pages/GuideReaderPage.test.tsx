import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import GuideReaderPage from "./GuideReaderPage";

const GUIDE = vi.hoisted(() => ({
  id: 1, slug: "robocop", title: "RoboCop", title_lead: "RoboCop", subtitle: null,
  category_id: null, category_label: null, series_id: null, model_id: null, scale: "1:6",
  status: "published", franchise: null, quote: null, creator_credit: null, light_source: null,
  philosophy_note: null, paint_lines_used: [], technique_tags: [], character_brief: null,
  theme: null, head_style: null, thinning_config: null,
  tabs: [{ id: 1, name: "Metals", dom_id: null, sort_order: 0, has_expert_subtab: false,
    section: null, value_map: null, subtabs: [], method_block: null, phases: [] }],
  created_at: null, updated_at: null, published_at: null,
}));

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: { painting: { guides: { get: vi.fn().mockResolvedValue(GUIDE) } } },
  };
});

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/painting/guides/${id}`]}>
      <Routes>
        <Route path="/painting/guides/:id" element={<GuideReaderPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("GuideReaderPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the guide and a Print button that triggers window.print (#262)", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    renderAt("1");

    // Reader mounted (hero h1 from the fetched guide).
    expect(await screen.findByRole("heading", { level: 1, name: /RoboCop/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /print/i }));
    expect(printSpy).toHaveBeenCalledTimes(1);
    printSpy.mockRestore();
  });

  it("surfaces a load error", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.get).mockRejectedValueOnce(new Error("boom"));
    renderAt("1");
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
