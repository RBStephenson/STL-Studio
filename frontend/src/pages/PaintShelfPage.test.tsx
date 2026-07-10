import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
        inventory: {
          importPreview: vi.fn(),
          importConfirm: vi.fn(),
          exportCsv: vi.fn().mockResolvedValue(undefined),
        },
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

  it("shows the dashed empty-state panel with an Add-paint CTA when the shelf has no paints", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.paints.list).mockResolvedValueOnce({ total: 0, page: 1, page_size: 48, items: [] });
    renderPage();

    expect(await screen.findByText("Your shelf is empty")).toBeInTheDocument();
    expect(screen.getByText(/Import CSV with a PaintRack export/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();

    const addButtons = screen.getAllByRole("button", { name: /add paint/i });
    expect(addButtons).toHaveLength(2); // header CTA + empty-state CTA
    await userEvent.click(addButtons[1]);
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument(); // add-paint form mounted
  });

  it("shows a distinct 'no match' empty state when filters exclude everything", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.paints.list).mockResolvedValueOnce({ total: 0, page: 1, page_size: 48, items: [] });
    renderPage();
    await screen.findByText("Your shelf is empty");

    vi.mocked(api.painting.paints.list).mockResolvedValueOnce({ total: 0, page: 1, page_size: 48, items: [] });
    fireEvent.change(screen.getByPlaceholderText("Search name or code…"), { target: { value: "zzz" } });

    expect(await screen.findByText("No paints match")).toBeInTheDocument();
    // Only the header CTA remains — the empty-state CTA is filter-scoped, not shown for "no match".
    expect(screen.getAllByRole("button", { name: /add paint/i })).toHaveLength(1);
  });

  it("shows the shared error state on a list-fetch failure, with a working Retry", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.paints.list).mockRejectedValueOnce(new Error("Backend unreachable"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unreachable");
    expect(screen.getByText("Couldn't load the paint shelf")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();

    vi.mocked(api.painting.paints.list).mockResolvedValueOnce({
      total: 2, page: 1, page_size: 48, items: PAINTS,
    });
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Coal Black")).toBeInTheDocument();
  });

  it("lists paints with chips, line labels, and owned state", async () => {
    renderPage();

    expect(await screen.findByText("Coal Black")).toBeInTheDocument();
    expect(screen.getByText("Mystery Mix")).toBeInTheDocument();
    expect(screen.getByTestId("color-chip")).toBeInTheDocument();        // Coal Black
    expect(screen.getByTestId("color-chip-empty")).toBeInTheDocument();  // Mystery Mix
    expect(screen.getAllByText("Monument Hobbies — Pro Acryl Standard")).toHaveLength(2);
  });

  it("links the header help icon to the Paint Shelf Help section", async () => {
    renderPage();
    await screen.findByText("Coal Black");

    expect(screen.getByRole("link", { name: /how the paint shelf works/i }))
      .toHaveAttribute("href", "/help#paint-shelf");
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

  it("shows a code-pattern 422 inline and keeps the form open (#244)", async () => {
    const { api } = await import("../api/client");
    const detail = "Code 'XYZ' does not match the line's code pattern '^MPA-\\d{3}$'";
    vi.mocked(api.painting.paints.create).mockRejectedValue(new Error(detail));
    renderPage();
    await screen.findByText("Coal Black");

    await userEvent.click(screen.getByRole("button", { name: /add paint/i }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Paint line" }), "10");
    await userEvent.type(screen.getByPlaceholderText("002"), "XYZ");
    await userEvent.type(screen.getByPlaceholderText("Coal Black"), "Bad Code Red");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    // Form stays open with the typed values so the code can be corrected.
    expect(screen.getByPlaceholderText("002")).toHaveValue("XYZ");

    // The error clears when the form is reopened.
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    await userEvent.click(screen.getByRole("button", { name: /add paint/i }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens the edit form pre-filled when the row Edit button is clicked (#273)", async () => {
    renderPage();
    await screen.findByText("Coal Black");

    // Two rows, each with an Edit button (always in the DOM, hover-revealed).
    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);

    // The form mounts pre-filled with the clicked paint's values.
    expect(screen.getByPlaceholderText("002")).toHaveValue("002");
    expect(screen.getByPlaceholderText("Coal Black")).toHaveValue("Coal Black");
  });

  it("edits a paint without overwriting its source (#273)", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.paints.update).mockResolvedValue(PAINTS[0]);
    renderPage();
    await screen.findByText("Coal Black");

    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    const nameInput = screen.getByPlaceholderText("Coal Black");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Coal Black v2");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(api.painting.paints.update).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ name: "Coal Black v2" })
      );
    });
    // `source` must NOT be sent on edit — it would un-mark imported paints.
    const body = vi.mocked(api.painting.paints.update).mock.calls[0][1];
    expect(body).not.toHaveProperty("source");
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

describe("PaintShelfPage - PaintRack CSV import (#242)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  const DIFF = {
    added: [{ brand: "Pro Acryl", code: "MPA-018", name: "Light Umber", paint_class: "" }],
    changed: [{
      brand: "Pro Acryl", code: "MPA-002", name: "Coal Black v2", paint_class: "",
      paint_id: 1, changes: { name: { from: "Coal Black", to: "Coal Black v2" } },
    }],
    removed: [{ brand: "Dirty Down", code: "", name: "Rust", paint_class: "", paint_id: 9 }],
    warnings: [],
    summary: { rows: 2, added: 1, changed: 1, removed: 1, warnings: 0 },
  };

  async function pickFile() {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.inventory.importPreview).mockResolvedValue(DIFF);
    renderPage();
    await screen.findByText("Coal Black");
    const file = new File(["Brand,SKU,Paint Name,Paint Class,Size,Count\n"], "paintRack.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByTestId("csv-file-input"), file);
    return { api, file };
  }

  it("shows the diff preview without applying anything", async () => {
    const { api } = await pickFile();

    expect(await screen.findByTestId("import-diff-modal")).toBeInTheDocument();
    expect(screen.getByText(/1 new/)).toBeInTheDocument();
    expect(screen.getByText(/1 changed/)).toBeInTheDocument();
    expect(screen.getByText("added (1)")).toBeInTheDocument();
    expect(api.painting.inventory.importConfirm).not.toHaveBeenCalled();
  });

  it("confirm applies adds+changes, and removals only when opted in", async () => {
    const { api, file } = await pickFile();
    vi.mocked(api.painting.inventory.importConfirm).mockResolvedValue({
      ok: true, applied: { added: 1, changed: 1, removed: 1 },
    });
    await screen.findByTestId("import-diff-modal");

    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /apply import/i }));

    await waitFor(() => {
      expect(api.painting.inventory.importConfirm).toHaveBeenCalledWith(
        file, { added: true, changed: true, removed: true }
      );
    });
    expect(screen.queryByTestId("import-diff-modal")).toBeNull();
  });

  it("renders code warnings in the preview without blocking apply (#244)", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.inventory.importPreview).mockResolvedValue({
      ...DIFF,
      warnings: [{
        brand: "Pro Acryl", code: "OOPS-1", name: "Bad Black", paint_class: "PRIME",
        message: "Code 'OOPS-1' does not match the line's code pattern '^MPAP-\\d{3}$'",
      }],
      summary: { ...DIFF.summary, warnings: 1 },
    });
    renderPage();
    await screen.findByText("Coal Black");
    const file = new File(["Brand,SKU,Paint Name,Paint Class,Size,Count\n"], "paintRack.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByTestId("csv-file-input"), file);

    await screen.findByTestId("import-diff-modal");
    const warnings = screen.getByTestId("import-warnings");
    expect(warnings).toHaveTextContent("code warnings (1)");
    expect(warnings).toHaveTextContent("OOPS-1");
    expect(screen.getByRole("button", { name: /apply import/i })).toBeEnabled();
  });

  it("cancel closes the modal without applying", async () => {
    const { api } = await pickFile();
    await screen.findByTestId("import-diff-modal");

    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByTestId("import-diff-modal")).toBeNull();
    expect(api.painting.inventory.importConfirm).not.toHaveBeenCalled();
  });
});
