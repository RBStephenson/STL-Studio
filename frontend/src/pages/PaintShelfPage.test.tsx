import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import PaintShelfPage, { ColorChip } from "./PaintShelfPage";

// vi.mock factories are hoisted above module-level consts, so the fixture
// data they reference must be hoisted too.
const PAINTS = vi.hoisted(() => [
  {
    id: 1, paint_line_id: 10, code: "002", name: "Coal Black", hex: "#2A2A2A",
    value_pct: null, finish: "matte", matchable: true, owned: true,
    handling_flags: [], substitute_for: [], notes: null, source: "manual",
  },
  {
    id: 2, paint_line_id: 10, code: "S18", name: "Mystery Mix", hex: null,
    value_pct: null, finish: "wash", matchable: false, owned: false,
    handling_flags: [], substitute_for: [], notes: null, source: "manual",
  },
]);

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      painting: {
        brands: {
          list: vi.fn().mockResolvedValue([
            {
              id: 5, name: "Monument Hobbies",
              lines: [{ id: 10, brand_id: 5, name: "Pro Acryl Standard", code_pattern: null }],
            },
          ]),
          create: vi.fn(),
        },
        lines: { create: vi.fn() },
        paints: {
          list: vi.fn().mockResolvedValue({ total: 2, page: 1, page_size: 48, items: PAINTS }),
          create: vi.fn(),
          update: vi.fn(),
          delete: vi.fn(),
        },
      },
    },
  };
});

vi.mock("../context/ToastContext", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <PaintShelfPage />
    </MemoryRouter>
  );
}

describe("ColorChip", () => {
  it("renders the paint hex as the chip background", () => {
    render(<ColorChip hex="#2A2A2A" />);
    const chip = screen.getByTestId("color-chip");
    expect(chip.style.backgroundColor).toBe("rgb(42, 42, 42)");
    expect(chip).toHaveAttribute("title", "#2A2A2A");
  });

  it("renders a placeholder when hex is missing", () => {
    render(<ColorChip hex={null} />);
    expect(screen.getByTestId("color-chip-empty")).toBeInTheDocument();
  });
});

describe("PaintShelfPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("lists paints with chips, line labels, and owned state", async () => {
    renderPage();

    expect(await screen.findByText("Coal Black")).toBeInTheDocument();
    expect(screen.getByText("Mystery Mix")).toBeInTheDocument();
    expect(screen.getByTestId("color-chip")).toBeInTheDocument();        // Coal Black
    expect(screen.getByTestId("color-chip-empty")).toBeInTheDocument();  // Mystery Mix
    expect(screen.getAllByText("Monument Hobbies — Pro Acryl Standard")).toHaveLength(2);
  });

  it("passes filters to the API when changed", async () => {
    const { api } = await import("../api/client");
    renderPage();
    await screen.findByText("Coal Black");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Finish" }), "wash");
    await waitFor(() => {
      expect(api.painting.paints.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ finish: "wash" })
      );
    });

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Owned" }), "1");
    await waitFor(() => {
      expect(api.painting.paints.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ finish: "wash", owned: true })
      );
    });
  });

  it("searches by name or code", async () => {
    const { api } = await import("../api/client");
    renderPage();
    await screen.findByText("Coal Black");

    await userEvent.type(screen.getByPlaceholderText(/search name or code/i), "black");
    await waitFor(() => {
      expect(api.painting.paints.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "black" })
      );
    });
  });

  it("creates a paint through the add form", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.paints.create).mockResolvedValue(PAINTS[0]);
    renderPage();
    await screen.findByText("Coal Black");

    await userEvent.click(screen.getByRole("button", { name: /add paint/i }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Paint line" }), "10");
    await userEvent.type(screen.getByPlaceholderText("002"), "018");
    await userEvent.type(screen.getByPlaceholderText("Coal Black"), "Bold Pyrrole Red");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(api.painting.paints.create).toHaveBeenCalledWith(
        expect.objectContaining({
          paint_line_id: 10,
          code: "018",
          name: "Bold Pyrrole Red",
          finish: "matte",
          owned: true,
          source: "manual",
        })
      );
    });
  });
});
