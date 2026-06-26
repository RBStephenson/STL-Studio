import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ColorMatchStudioPage from "./ColorMatchStudioPage";

const matchResult = {
  caveat: "Inventory hexes are approximate — confirm by eye under your bench light.",
  regions: [
    {
      hex: "#C81E1E",
      lab: [40, 60, 50] as [number, number, number],
      value_l: 40,
      weight: 0.6,
      value_candidates: [
        { paint_id: 1, code: "R01", name: "Bold Red", brand: "Pro Acryl", line: "Std",
          hex: "#C81E1E", finish: "matte", delta_l: 1.2, delta_e: 1.5, band: "very_close" as const },
        { paint_id: 2, code: "M01", name: "Gunmetal", brand: "Pro Acryl", line: "Std",
          hex: "#5A5A5A", finish: "metallic", delta_l: 3.0, delta_e: null, band: "close" as const },
      ],
      hue_candidates: [
        { paint_id: 1, code: "R01", name: "Bold Red", brand: "Pro Acryl", line: "Std",
          hex: "#C81E1E", finish: "matte", delta_l: 1.2, delta_e: 1.5, band: "very_close" as const },
      ],
      glaze_options: [
        { paint_id: 3, code: "I01", name: "Red Shade", brand: "Pro Acryl", line: "Wash",
          hex: "#7A1010", finish: "ink", delta_l: 6.0, delta_e: 7.2, band: "family" as const },
      ],
    },
  ],
};

const colorMatch = vi.fn().mockResolvedValue(matchResult);

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return { ...orig, api: { painting: { colorMatch: (...a: unknown[]) => colorMatch(...a) } } };
});

vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

function renderPage() {
  return render(<MemoryRouter><ColorMatchStudioPage /></MemoryRouter>);
}

async function uploadImage() {
  const input = screen.getByTestId("colormatch-input");
  await userEvent.upload(input, new File(["x"], "ref.png", { type: "image/png" }));
}

describe("ColorMatchStudioPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom has no object-URL support; the page calls it for the preview.
    globalThis.URL.createObjectURL = vi.fn(() => "blob:preview");
  });

  it("matches an uploaded image and renders value, hue, and glaze suggestions", async () => {
    renderPage();
    await uploadImage();

    expect(await screen.findByTestId("colormatch-region")).toBeInTheDocument();
    expect(colorMatch).toHaveBeenCalledOnce();

    // Section headings + the value-first lead.
    expect(screen.getByText("Value match")).toBeInTheDocument();
    expect(screen.getByText("Hue match")).toBeInTheDocument();
    expect(screen.getByText("Glazes & washes")).toBeInTheDocument();

    // Candidates by class: metallic only in value, ink only in glaze.
    expect(screen.getAllByText("Bold Red").length).toBeGreaterThan(0);
    expect(screen.getByText("Gunmetal")).toBeInTheDocument();
    expect(screen.getByText("Red Shade")).toBeInTheDocument();
  });

  it("always shows the confirm-by-eye caveat", async () => {
    renderPage();
    await uploadImage();
    expect(await screen.findByText(/confirm by eye/i)).toBeInTheDocument();
  });

  it("toggles value mode", async () => {
    renderPage();
    await uploadImage();

    const toggle = await screen.findByRole("button", { name: /value mode/i });
    expect(toggle).toHaveAttribute("aria-pressed", "true"); // value-first default
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  it("is suggest-only — offers no assign/apply action", async () => {
    renderPage();
    await uploadImage();
    await screen.findByTestId("colormatch-region");
    expect(screen.queryByRole("button", { name: /assign|apply/i })).toBeNull();
  });
});
