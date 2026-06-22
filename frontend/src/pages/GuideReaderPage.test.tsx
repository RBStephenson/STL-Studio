import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import GuideReaderPage from "./GuideReaderPage";
import { ToastProvider } from "../context/ToastContext";
import { ConfirmProvider } from "../context/ConfirmContext";

const navigateSpy = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => {
  const orig = await importOriginal<typeof import("react-router-dom")>();
  return { ...orig, useNavigate: () => navigateSpy };
});

const GUIDE = vi.hoisted(() => ({
  id: 1, slug: "robocop", title: "RoboCop", title_lead: "RoboCop", subtitle: null,
  category_id: null, category_label: null, series_id: null, model_id: null, scale: "1:6",
  status: "published", franchise: null, quote: null, creator_credit: null, light_source: null,
  philosophy_note: null, paint_lines_used: [], technique_tags: [], character_brief: null,
  theme: null, head_style: null, thinning_config: null,
  tabs: [{ id: 1, name: "Metals", dom_id: null, sort_order: 0, has_expert_subtab: false,
    section: null, value_map: null, subtabs: [], callouts: [], method_block: null, phases: [] }],
  created_at: null, updated_at: null, published_at: null,
}));

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      painting: {
        guides: {
          get: vi.fn().mockResolvedValue(GUIDE),
          update: vi.fn(),
          delete: vi.fn().mockResolvedValue({ ok: true }),
          exportPdf: vi.fn().mockResolvedValue(undefined),
        },
      },
    },
  };
});

function renderAt(id: string) {
  return render(
    <ToastProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[`/painting/guides/${id}`]}>
          <Routes>
            <Route path="/painting/guides/:id" element={<GuideReaderPage />} />
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </ToastProvider>
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

  it("exports a PDF via the Export PDF menu (#320/#511)", async () => {
    const { api } = await import("../api/client");
    renderAt("1");
    await screen.findByRole("heading", { level: 1, name: /RoboCop/ });

    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: /export this guide/i }));
    expect(api.painting.guides.exportPdf).toHaveBeenCalledWith(
      1, "robocop", expect.objectContaining({ footer: true, watermark: false }),
    );
  });

  it("surfaces a PDF export failure as a toast (#320)", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.exportPdf).mockRejectedValueOnce(
      new Error("PDF rendering needs Chromium")
    );
    renderAt("1");
    await screen.findByRole("heading", { level: 1, name: /RoboCop/ });

    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: /export this guide/i }));
    expect(await screen.findByText(/needs Chromium/i)).toBeInTheDocument();
  });

  it("shows a View-model link only when the guide is linked to a model (#263)", async () => {
    const { api } = await import("../api/client");
    // default fixture has model_id null → no link
    renderAt("1");
    await screen.findByRole("heading", { level: 1, name: /RoboCop/ });
    expect(screen.queryByRole("link", { name: /view model/i })).toBeNull();

    vi.mocked(api.painting.guides.get).mockResolvedValueOnce({ ...GUIDE, model_id: 42 });
    renderAt("1");
    const link = await screen.findByRole("link", { name: /view model/i });
    expect(link).toHaveAttribute("href", "/models/42");
  });

  it("surfaces a load error", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.get).mockRejectedValueOnce(new Error("boom"));
    renderAt("1");
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("publishes a draft guide (#277)", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.get).mockResolvedValueOnce({ ...GUIDE, status: "draft" });
    vi.mocked(api.painting.guides.update).mockResolvedValueOnce({ ...GUIDE, status: "published" });
    renderAt("1");

    const publishBtn = await screen.findByRole("button", { name: /^publish$/i });
    await userEvent.click(publishBtn);

    expect(api.painting.guides.update).toHaveBeenCalledWith(1, { status: "published" });
    // Button flips to Unpublish once published.
    expect(await screen.findByRole("button", { name: /unpublish/i })).toBeInTheDocument();
  });

  it("deletes a guide after confirmation and navigates away (#277)", async () => {
    const { api } = await import("../api/client");
    renderAt("1");
    await screen.findByRole("heading", { level: 1, name: /RoboCop/ });

    await userEvent.click(screen.getByRole("button", { name: /delete/i }));
    // Confirm dialog → click its destructive action.
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(api.painting.guides.delete).toHaveBeenCalledWith(1);
    expect(navigateSpy).toHaveBeenCalledWith("/painting/guides");
  });
});
