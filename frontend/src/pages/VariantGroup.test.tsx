import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import VariantGroup from "./VariantGroup";
import { QueryWrapper } from "../test/queryWrapper";

const MODEL = {
  id: 1, name: "widget.stl", title: "Widget", thumbnail_path: null, thumbnail_url: null,
  creator_id: 5, character: "Widget", auto_tags: [], tags: [], needs_review: false,
};

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      ...orig.api,
      fileUrl: (p: string) => p,
      models: {
        ...orig.api.models,
        variants: vi.fn(async () => ({ items: [MODEL] })),
        characters: vi.fn(async () => []),
      },
    },
  };
});
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));

function renderPage() {
  return render(
    <QueryWrapper>
      <MemoryRouter initialEntries={["/groups/5/Widget"]}>
        <Routes>
          <Route path="/groups/:creatorId/:character" element={<VariantGroup />} />
        </Routes>
      </MemoryRouter>
    </QueryWrapper>
  );
}

describe("VariantGroup empty state", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the dashed empty-state panel when the group has zero variants on initial load", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.variants).mockResolvedValueOnce({ items: [] } as unknown as Awaited<ReturnType<typeof api.models.variants>>);
    renderPage();

    expect(await screen.findByText("No variants found")).toBeInTheDocument();
    expect(screen.getByText(/moved or removed elsewhere/)).toBeInTheDocument();
  });
});

describe("VariantGroup error state", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the shared error state on load failure, with a working Retry", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.variants).mockRejectedValueOnce(new Error("Network down"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Network down");
    expect(screen.getByText("Couldn't load this variant group")).toBeInTheDocument();

    vi.mocked(api.models.variants).mockResolvedValueOnce({ items: [MODEL] } as unknown as Awaited<ReturnType<typeof api.models.variants>>);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findAllByText("Widget")).not.toHaveLength(0);
  });
});
