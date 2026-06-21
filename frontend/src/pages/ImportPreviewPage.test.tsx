import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ImportPreviewPage from "./ImportPreviewPage";

vi.mock("../api/client", () => ({
  api: {
    import: {
      sourceContents: vi.fn(),
      libraries: vi.fn(),
      getMapping: vi.fn(),
      setMapping: vi.fn().mockResolvedValue({ source_path: "/src", library_id: 1 }),
      preview: vi.fn(),
      scanFolder: vi.fn().mockResolvedValue({ running: true, message: "importing" }),
      apply: vi.fn().mockResolvedValue({
        manifest_id: "m1", moved_models: 1, moved_files: 2, skipped: 0, ineligible: [], undo_log: null,
      }),
    },
    scan: {
      libraries: vi.fn(),
      status: vi.fn().mockResolvedValue({ running: false, message: "done" }),
    },
    models: {
      bulkEnrich: vi.fn().mockResolvedValue({ ok: true, updated: 2 }),
      bulkTag: vi.fn().mockResolvedValue({ ok: true, updated: 2 }),
    },
  },
}));

const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

import { api } from "../api/client";

const PACK = {
  name: "PackA", source_path: "/src/PackA", file_count: 0, model_ids: [1, 2],
  creator_name: null, title: null, character: null, notes: null, source_url: null, tags: [],
};

function setup(opts: { mapping?: { source_path: string; library_id: number } | null } = {}) {
  vi.mocked(api.import.sourceContents).mockResolvedValue({
    source: "/src", is_flat: false, file_count: 0,
    entries: [{ name: "PackA", path: "/src/PackA", already_imported: false, file_count: 212 }],
  });
  vi.mocked(api.scan.libraries).mockResolvedValue([
    { id: 1, path: "/lib", name: "minis", is_writable: true, write_enabled: false },
  ]);
  vi.mocked(api.import.getMapping).mockResolvedValue(opts.mapping ?? null);
  vi.mocked(api.import.preview).mockResolvedValue({ source: "/src", library_id: null, packs: [PACK] });

  return render(
    <MemoryRouter initialEntries={["/import/preview?source=/src"]}>
      <ImportPreviewPage />
    </MemoryRouter>
  );
}

describe("ImportPreviewPage (#452 C2)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders a card per pack from source-contents", async () => {
    setup();
    expect(await screen.findByText("PackA")).toBeInTheDocument();
    expect(screen.getByText("/src/PackA")).toBeInTheDocument();
  });

  it("shows the recursive STL file count on each pack card (#456)", async () => {
    setup();
    await screen.findByText("PackA");
    expect(screen.getByTestId("pack-file-count")).toHaveTextContent("212 files");
  });

  it("lists writable libraries in the destination dropdown", async () => {
    setup();
    await screen.findByText("PackA");
    expect(screen.getByRole("option", { name: "minis" })).toBeInTheDocument();
  });

  it("prefills the destination from the saved mapping", async () => {
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await screen.findByText("PackA");
    expect((screen.getByLabelText("Library") as HTMLSelectElement).value).toBe("1");
  });

  it("Import is disabled until a library is chosen", async () => {
    setup();
    await screen.findByText("PackA");
    expect(screen.getByRole("button", { name: /^import$/i })).toBeDisabled();
  });

  it("persists the mapping when a library is selected", async () => {
    setup();
    await screen.findByText("PackA");
    fireEvent.change(screen.getByLabelText("Library"), { target: { value: "1" } });
    await waitFor(() => expect(api.import.setMapping).toHaveBeenCalledWith("/src", 1));
  });

  it("shows the batch bar for imported packs and applies via /import/apply", async () => {
    vi.mocked(api.import.sourceContents).mockResolvedValue({
      source: "/src", is_flat: false, file_count: 0,
      entries: [{ name: "PackA", path: "/src/PackA", already_imported: true, file_count: 5 }],
    });
    vi.mocked(api.scan.libraries).mockResolvedValue([
      { id: 1, path: "/lib", name: "minis", is_writable: true, write_enabled: true },
    ]);
    vi.mocked(api.import.getMapping).mockResolvedValue({ source_path: "/src", library_id: 1 });
    vi.mocked(api.import.preview).mockResolvedValue({ source: "/src", library_id: 1, packs: [PACK] });

    render(
      <MemoryRouter initialEntries={["/import/preview?source=/src"]}>
        <ImportPreviewPage />
      </MemoryRouter>
    );

    const moveBtn = await screen.findByRole("button", { name: /move to minis/i });
    fireEvent.click(moveBtn);
    await waitFor(() => expect(api.import.apply).toHaveBeenCalledWith("/src"));
  });

  it("imports a pack: scan, then enrich the ingested models", async () => {
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await screen.findByText("PackA");

    // Expand and set a creator so bulkEnrich receives a field.
    fireEvent.click(screen.getByLabelText("Expand"));
    fireEvent.change(await screen.findByPlaceholderText("Creator name"), { target: { value: "Hijos De Pulvo" } });

    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(() => expect(api.import.scanFolder).toHaveBeenCalledWith("/src/PackA"));
    await waitFor(
      () => expect(api.models.bulkEnrich).toHaveBeenCalledWith([1, 2], { creator_name: "Hijos De Pulvo" }),
      { timeout: 5000 }
    );
    expect(await screen.findByText("Imported", {}, { timeout: 5000 })).toBeInTheDocument();
  });
});
