import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GuideExportMenu from "./GuideExportMenu";
import { Guide } from "../../api/client";

vi.mock("../../api/client", async (orig) => {
  const mod = await orig<typeof import("../../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      painting: {
        ...mod.api.painting,
        guides: {
          ...mod.api.painting.guides,
          exportPdf: vi.fn().mockResolvedValue(undefined),
          exportSeriesPdf: vi.fn().mockResolvedValue(undefined),
        },
      },
    },
  };
});

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

import { api } from "../../api/client";

const exportPdf = api.painting.guides.exportPdf as ReturnType<typeof vi.fn>;
const exportSeriesPdf = api.painting.guides.exportSeriesPdf as ReturnType<typeof vi.fn>;

function makeGuide(over: Partial<Guide> = {}): Guide {
  return { id: 7, slug: "presto", series_id: null, ...over } as Guide;
}

function renderMenu(guide: Guide) {
  return render(<GuideExportMenu guide={guide} busy={false} setBusy={vi.fn()} />);
}

describe("GuideExportMenu", () => {
  beforeEach(() => {
    exportPdf.mockClear();
    exportSeriesPdf.mockClear();
  });

  it("exports a single guide with default stamping (footer on, watermark off)", async () => {
    const user = userEvent.setup();
    renderMenu(makeGuide());
    await user.click(screen.getByRole("button", { name: /export pdf/i }));
    await user.click(screen.getByRole("menuitem", { name: /export this guide/i }));
    expect(exportPdf).toHaveBeenCalledWith(7, "presto", { footer: true, watermark: false });
  });

  it("hides the series-bundle action when the guide has no series", async () => {
    const user = userEvent.setup();
    renderMenu(makeGuide({ series_id: null }));
    await user.click(screen.getByRole("button", { name: /export pdf/i }));
    expect(screen.queryByRole("menuitem", { name: /series bundle/i })).toBeNull();
  });

  it("exports the series bundle with cover + tier when the guide is in a series", async () => {
    const user = userEvent.setup();
    renderMenu(makeGuide({ series_id: 3 }));
    await user.click(screen.getByRole("button", { name: /export pdf/i }));
    await user.type(screen.getByPlaceholderText(/hero tier/i), "Hero Tier");
    await user.click(screen.getByRole("menuitem", { name: /series bundle/i }));
    expect(exportSeriesPdf).toHaveBeenCalledWith(3, {
      footer: true,
      watermark: false,
      tier: "Hero Tier",
      cover: true,
    });
  });

  it("passes watermark on when toggled", async () => {
    const user = userEvent.setup();
    renderMenu(makeGuide());
    await user.click(screen.getByRole("button", { name: /export pdf/i }));
    await user.click(screen.getByLabelText(/diagonal watermark/i));
    await user.click(screen.getByRole("menuitem", { name: /export this guide/i }));
    expect(exportPdf).toHaveBeenCalledWith(7, "presto", { footer: true, watermark: true });
  });
});
