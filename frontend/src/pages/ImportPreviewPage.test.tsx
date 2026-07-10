import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ImportPreviewPage, { ImageRotator } from "./ImportPreviewPage";

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
        started: false,
        result: { manifest_id: "m1", moved_models: 1, moved_files: 2, skipped: 0, ineligible: [], undo_log: null },
      }),
      applyStatus: vi.fn().mockResolvedValue({
        running: false, message: "done", moved_files: 2, total_files: 2, error: null,
        result: { manifest_id: "m1", moved_models: 1, moved_files: 2, skipped: 0, ineligible: [], undo_log: null },
      }),
      downloadImages: vi.fn().mockResolvedValue({ started: false, result: { downloaded: 0 } }),
      downloadImagesStatus: vi.fn().mockResolvedValue({
        running: false, message: "done", downloaded: 0, total: 0, error: null, result: { downloaded: 0 },
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

// This page imports a heavy component tree and each test drives several awaited
// mock promises through React renders. Under a loaded parallel CI runner the
// test's own scheduler is starved, so an element can take >5s of wall-clock to
// appear even though the mocks resolve instantly — the inner 5000ms findBy waits
// then time out (#596). Inner waits use _WAIT (10s), comfortably under the 15s
// per-test cap, so a genuinely-missing element still fails with a useful message.
vi.setConfig({ testTimeout: 15000, hookTimeout: 15000 });
const _WAIT = 10000;

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
  return screen.findByText("PackA", {}, { timeout: _WAIT });
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
      { timeout: _WAIT }
    );
    expect(await screen.findByText("Imported", {}, { timeout: _WAIT })).toBeInTheDocument();
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
      { timeout: _WAIT }
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

  it("persists source_site scraped from the storefront through to bulkEnrich", async () => {
    // Regression: source_site was captured from the scrape response but never
    // sent to bulkEnrich, so it was silently dropped even though the user
    // provided a recognised store URL.
    vi.mocked(api.scrape.fetchUrl).mockResolvedValue({
      title: "Scraped Title", description: null, source_url: "https://cults3d.com/x",
      source_site: "cults3d", external_id: null, creator_name: "Scraped Creator",
      thumbnail_url: null, image_urls: [], tags: [], category: null, license: null,
      like_count: null, download_count: null,
    });
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByLabelText("Expand"));

    fireEvent.change(await screen.findByPlaceholderText("https://…"), { target: { value: "https://cults3d.com/x" } });
    fireEvent.click(screen.getByRole("button", { name: /fetch/i }));
    await waitFor(() => expect(api.scrape.fetchUrl).toHaveBeenCalledWith("https://cults3d.com/x"));
    await screen.findByDisplayValue("Scraped Title");

    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(
      () => expect(api.models.bulkEnrich).toHaveBeenCalledWith(
        [1, 2], expect.objectContaining({ source_site: "cults3d" }),
      ),
      { timeout: _WAIT },
    );
  });

  it("polls download-images status and shows downloading progress for a background job", async () => {
    vi.mocked(api.scrape.fetchUrl).mockResolvedValue({
      title: "Scraped Title", description: null, source_url: "https://cults3d.com/x",
      source_site: "cults3d", external_id: null, creator_name: "Scraped Creator",
      thumbnail_url: "https://cdn.example/cover.jpg", image_urls: [], tags: [], category: null,
      license: null, like_count: null, download_count: null,
    });
    vi.mocked(api.import.downloadImages).mockResolvedValue({ started: true, result: null });
    vi.mocked(api.import.downloadImagesStatus)
      .mockResolvedValueOnce({
        running: true, message: "Downloading images (0/1)", downloaded: 0, total: 1, error: null, result: null,
      })
      .mockResolvedValue({
        running: false, message: "done", downloaded: 1, total: 1, error: null, result: { downloaded: 1 },
      });

    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByLabelText("Expand"));
    fireEvent.change(await screen.findByPlaceholderText("https://…"), { target: { value: "https://cults3d.com/x" } });
    fireEvent.click(screen.getByRole("button", { name: /fetch/i }));
    await screen.findByDisplayValue("Scraped Title");

    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    expect(await screen.findByText(/downloading 0\/1 images/i, {}, { timeout: _WAIT })).toBeInTheDocument();
    expect(await screen.findByText("Imported", {}, { timeout: _WAIT })).toBeInTheDocument();
  });

  it("scopes the move to the pack's own path, not the top-level import source", async () => {
    // Regression: apply used to be called with the whole import root, which
    // could sweep in every other pending pack under that root, not just the
    // one being imported.
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(
      () => expect(api.import.apply).toHaveBeenCalledWith("/src/PackA"),
      { timeout: _WAIT },
    );
    expect(api.import.apply).not.toHaveBeenCalledWith("/src");
  });

  it("polls apply status and shows moving-files progress for a background job", async () => {
    vi.mocked(api.import.apply).mockResolvedValue({ started: true, result: null });
    vi.mocked(api.import.applyStatus)
      .mockResolvedValueOnce({
        running: true, message: "Moving files (1/2)", moved_files: 1, total_files: 2, error: null, result: null,
      })
      .mockResolvedValue({
        running: false, message: "done", moved_files: 2, total_files: 2, error: null,
        result: { manifest_id: "m1", moved_models: 1, moved_files: 2, skipped: 0, ineligible: [], undo_log: null },
      });

    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    expect(await screen.findByText(/moving 1\/2 files/i, {}, { timeout: _WAIT })).toBeInTheDocument();
    expect(await screen.findByText("Imported", {}, { timeout: _WAIT })).toBeInTheDocument();
  });

  it("surfaces a background-job error as a toast", async () => {
    vi.mocked(api.import.apply).mockResolvedValue({ started: true, result: null });
    vi.mocked(api.import.applyStatus).mockResolvedValue({
      running: false, message: "error", moved_files: 0, total_files: 0,
      error: "destination already exists", result: null,
    });

    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(
      () => expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("destination already exists"), "error"),
      { timeout: _WAIT },
    );
  });

  it("assigns the pack to a selected collection after ingest (#458)", async () => {
    setup({ mapping: { source_path: "/src", library_id: 1 } });
    await scan();
    fireEvent.click(screen.getByLabelText("Expand"));

    fireEvent.click(await screen.findByRole("button", { name: "Heroes" }));
    fireEvent.click(screen.getByRole("button", { name: /^import$/i }));

    await waitFor(
      () => expect(api.collections.bulkAddModels).toHaveBeenCalledWith(7, [1, 2]),
      { timeout: _WAIT }
    );
  });
});

describe("ImageRotator fade-timer cleanup on unmount (STUDIO-95)", () => {
  it("triggering a fade then unmounting does not update state after teardown", () => {
    vi.useFakeTimers();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { unmount } = render(<ImageRotator images={["a.png", "b.png"]} />);
    fireEvent.click(screen.getByLabelText("Next image")); // starts the 200ms fade-out/in cycle

    unmount();
    vi.advanceTimersByTime(200);

    expect(errorSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("Can't perform a React state update on an unmounted component")
    );
    errorSpy.mockRestore();
    vi.useRealTimers();
  });
});
