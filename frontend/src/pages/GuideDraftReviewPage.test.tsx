import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ApiError } from "../api/client";
import GuideDraftReviewPage from "./GuideDraftReviewPage";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (orig) => {
  const mod = await orig<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => mockNavigate, useParams: () => ({ id: "7" }) };
});

vi.mock("../api/client", async (orig) => {
  const mod = await orig<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      painting: {
        ...mod.api.painting,
        guides: {
          ...mod.api.painting.guides,
          get: vi.fn(),
          startDraft: vi.fn(),
          draftStatus: vi.fn(),
          update: vi.fn(),
        },
      },
    },
  };
});

// Stub the heavy display components — this page's logic is the poll/accept flow.
vi.mock("../components/guide/GuideReader", () => ({
  default: ({ guide }: { guide: { tabs: unknown[] } }) => (
    <div data-testid="reader">tabs:{guide.tabs.length}</div>
  ),
}));
vi.mock("../components/guide/GuideValidationPanel", () => ({
  default: ({ result }: { result: { flags: unknown[] } }) => (
    <div data-testid="validation">flags:{result.flags.length}</div>
  ),
}));
vi.mock("../components/guide/ReferenceImageUpload", () => ({
  default: () => <div data-testid="reference-upload" />,
}));
// Stub PaintPicker: a button that resolves to a fixed shelf paint.
vi.mock("../components/guide/PaintPicker", () => ({
  default: ({ onChange }: { onChange: (p: { id: number; name: string; code: string; hex: null }) => void }) => (
    <button onClick={() => onChange({ id: 9, name: "Matte White Primer", code: "MWP", hex: null })}>
      pick-paint
    </button>
  ),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

async function mocks() {
  const { api } = await import("../api/client");
  return vi.mocked(api.painting.guides);
}

const GUIDE = { id: 7, title: "Presto", tabs: [], reference_image_id: null };
const DRAFT_TABS = [{ name: "Skin", phases: [{ label: "Base", steps: [{ title: "Basecoat", swatches: [], mix_components: [] }] }] }];

function renderPage() {
  return render(
    <MemoryRouter>
      <GuideDraftReviewPage />
    </MemoryRouter>,
  );
}

describe("GuideDraftReviewPage (#492)", () => {
  beforeEach(() => vi.clearAllMocks());

  // Click the pre-gen "Generate draft" button once the guide has loaded.
  async function clickGenerate() {
    const btn = await screen.findByRole("button", { name: /generate draft/i });
    await userEvent.click(btn);
  }

  it("shows the pre-gen panel with the reference-image control", async () => {
    const g = await mocks();
    g.get.mockResolvedValue(GUIDE as never);
    renderPage();

    expect(await screen.findByTestId("reference-upload")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate draft/i })).toBeInTheDocument();
    expect(g.startDraft).not.toHaveBeenCalled(); // no auto-start
  });

  it("generates on click, polls to done, then accepts into the editor", async () => {
    const g = await mocks();
    g.get.mockResolvedValue(GUIDE as never);
    g.startDraft.mockResolvedValue({
      status: "running", message: "generating", draft: null, flags: [], unresolved: [], error: null,
    } as never);
    g.draftStatus.mockResolvedValue({
      status: "done", message: "ready",
      draft: { tabs: DRAFT_TABS }, flags: [], unresolved: [], error: null,
    } as never);
    g.update.mockResolvedValue(GUIDE as never);

    renderPage();
    await clickGenerate();
    expect(g.startDraft).toHaveBeenCalledWith(7);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /accept into editor/i })).toBeInTheDocument(),
    );
    expect(screen.getByTestId("reader")).toHaveTextContent("tabs:1");

    await userEvent.click(screen.getByRole("button", { name: /accept into editor/i }));

    await waitFor(() => expect(g.update).toHaveBeenCalledWith(7, { tabs: DRAFT_TABS }));
    expect(mockNavigate).toHaveBeenCalledWith("/painting/guides/7/content");
  });

  it("resolves an unresolved paint and binds it on accept (#554)", async () => {
    const g = await mocks();
    g.get.mockResolvedValue(GUIDE as never);
    g.startDraft.mockResolvedValue({
      status: "running", message: "generating", draft: null, flags: [], unresolved: [], error: null,
    } as never);
    // Draft has a name-only swatch the matcher couldn't resolve.
    const draftTabs = [{ name: "Skin", phases: [{ label: "Base", steps: [{
      title: "Basecoat",
      swatches: [{ name: "Matt White Primer", value_pct: 80 }],
      mix_components: [],
    }] }] }];
    g.draftStatus.mockResolvedValue({
      status: "done", message: "ready", draft: { tabs: draftTabs }, flags: [],
      unresolved: [{ name: "Matt White Primer", tab: "Skin", step: "Basecoat" }], error: null,
    } as never);
    g.update.mockResolvedValue(GUIDE as never);

    renderPage();
    await clickGenerate();
    await screen.findByRole("button", { name: /accept into editor/i });

    // Bind the unresolved paint via the (stubbed) picker, then accept.
    await userEvent.click(screen.getByRole("button", { name: "pick-paint" }));
    await userEvent.click(screen.getByRole("button", { name: /accept into editor/i }));

    await waitFor(() => expect(g.update).toHaveBeenCalled());
    const sentTabs = g.update.mock.calls[0][1].tabs ?? [];
    const swatch = sentTabs[0]?.phases?.[0]?.steps?.[0]?.swatches?.[0];
    expect(swatch).toMatchObject({ paint_id: 9, name: null, value_pct: 80 });
  });

  it("surfaces a configure-key message on a 503", async () => {
    const g = await mocks();
    g.get.mockResolvedValue(GUIDE as never);
    g.startDraft.mockRejectedValue(new ApiError(503, "no key"));

    renderPage();
    await clickGenerate();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/no AI API key is configured/i),
    );
    expect(g.draftStatus).not.toHaveBeenCalled();
  });

  it("shows the generation error when the job fails", async () => {
    const g = await mocks();
    g.get.mockResolvedValue(GUIDE as never);
    g.startDraft.mockResolvedValue({
      status: "running", message: "generating", draft: null, flags: [], unresolved: [], error: null,
    } as never);
    g.draftStatus.mockResolvedValue({
      status: "error", message: "", draft: null, flags: [], unresolved: [], error: "model exploded",
    } as never);

    renderPage();
    await clickGenerate();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/model exploded/i),
    );
    expect(screen.queryByRole("button", { name: /accept into editor/i })).not.toBeInTheDocument();
  });
});
