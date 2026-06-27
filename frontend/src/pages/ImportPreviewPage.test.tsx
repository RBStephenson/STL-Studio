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
      downloadImages: vi.fn().mockResolvedValue(undefined),
    },
    scan: {
      libraries: vi.fn(),
      status: vi.fn().mockResolvedValue({ running: false, message: "done" }),
    },
    models: {
      bulkEnrich: vi.fn().mockResolvedValue({ ok: true, updated: 2 }),
      bulkTag: vi.fn().mockResolvedValue({ ok: true, updated: 2 }),
    },
    scrape: {
      fetchUrl: vi.fn(),
    },
    collections: {
      list: vi.fn(),
      create: vi.fn().mockResolvedValue({ id: 99, name: "New Col" }),
      bulkAddModels: vi.fn().mockResolvedValue(undefined),
    },
  },
}));

const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

import { api } from "../api/client";

const PACK = {
  name: "PackA", source_path: "/src/PackA", file_count: 0, model_ids: [1, 2],
  creator_name: null, title: null, character: null, notes: null, source_url: null, tags: [], images: [],
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
  vi.mocked(api.collections.list).mockResolvedValue([
    { id: 7, name: "Heroes", description: null, cover_image_path: null, model_count: 0, created_at: "" },
  ]);

  return render(
    <MemoryRouter initialEntries={["/import/preview?source=/src"]}>
      <ImportPreviewPage />
    </MemoryRouter>
  );
}

/** Click "Scan for New Files" and wait for the pack card to appear. */
async function scan() {
  fireEvent.click(await screen.findByRole("button", { name: /scan for new files/i }));
  return screen.findByText("PackA", {}, { timeout: 5000 });
}

describe("ImportPreviewPage (#452 C2)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders a card per pack from source-contents", async () => {
    setup();
    await scan();
    expect(screen.getByText("PackA")).toBeInTheDocument();
    expect(screen.getByText("/src/PackA")).toBeInTheDocument();
  });

  it("shows the recursive STL file count on each pack card (#456)", async () => {
    setup();
    await scan();
    expect(screen.getByTestId("pack-file-count")).toHaveTextContent("212 files");
  });

  it("lists writable libraries in the destination dropdown", async () => {
    setup();
    await scan();
    expect(screen.getByRole("option", { name: "minis" })).toBeInTheDocument();
  });

  it("prefills the destination from the saved mapping", async () => {
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    expect((screen.getByLabelText("Library") as HTMLSelectElement).value).toBe("1");
  });

  it("Import is disabled until a library is chosen", async () => {
    setup();
    await scan();
    expect(screen.getByRole("button", { name: /^import$/i })).toBeDisabled();
  });

  it("persists the mapping when a library is selected", async () => {
    setup();
    await scan();
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
    await scan();

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

  it("persists notes and source_url through bulkEnrich on import (#458)", async () => {
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByLabelText("Expand"));

    fireEvent.change(await screen.findByPlaceholderText("Notes about this pack…"), { target: { value: "Pack notes" } });
    fireEvent.change(screen.getByPlaceholderText("https://…"), { target: { value: "https://cults3d.com/x" } });
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(
      () => expect(api.models.bulkEnrich).toHaveBeenCalledWith(
        [1, 2], { notes: "Pack notes", source_url: "https://cults3d.com/x" },
      ),
      { timeout: 5000 }
    );
  });

  it("Fetch populates fields from the storefront scrape (#458)", async () => {
    vi.mocked(api.scrape.fetchUrl).mockResolvedValue({
      title: "Scraped Title", description: null, source_url: "https://cults3d.com/x",
      source_site: "cults3d", external_id: null, creator_name: "Scraped Creator",
      thumbnail_url: null, image_urls: [], tags: ["resin"], category: null, license: null,
      like_count: null, download_count: null,
    });
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByLabelText("Expand"));

    fireEvent.change(await screen.findByPlaceholderText("https://…"), { target: { value: "https://cults3d.com/x" } });
    fireEvent.click(screen.getByRole("button", { name: /fetch/i }));

    await waitFor(() => expect(api.scrape.fetchUrl).toHaveBeenCalledWith("https://cults3d.com/x"));
    expect(await screen.findByDisplayValue("Scraped Title")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Scraped Creator")).toBeInTheDocument();
  });

  it("assigns the pack to a selected collection after ingest (#458)", async () => {
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByLabelText("Expand"));

    fireEvent.click(await screen.findByRole("button", { name: "Heroes" }));
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(
      () => expect(api.collections.bulkAddModels).toHaveBeenCalledWith(7, [1, 2]),
      { timeout: 5000 }
    );
  });
});
