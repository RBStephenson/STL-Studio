import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import MetadataEditor from "./MetadataEditor";

const updateMock = vi.fn(async (..._args: unknown[]) => ({ ok: true }));
const fetchUrlMock = vi.fn(async (..._args: unknown[]) => ({}));
const applyImagesMock = vi.fn(async (..._args: unknown[]) => ({ ok: true, image_paths: [] }));
const toastMock = vi.fn();
const tagsMock = vi.fn(() => new Promise<never>(() => {}));

vi.mock("../api/client", () => ({
  api: {
    models: {
      tags: () => tagsMock(),
      update: (...a: unknown[]) => updateMock(...a),
    },
    scrape: {
      fetchUrl: (...a: unknown[]) => fetchUrlMock(...a),
      applyImages: (...a: unknown[]) => applyImagesMock(...a),
    },
  },
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

// Minimal ModelDetail stand-in — only the fields the editor reads.
const baseModel = {
  id: 5,
  title: "RoboCop",
  description: "",
  notes: "",
  source_url: "",
  source_site: "",
  license: "",
  category: "",
  creator: { name: "CA3D" },
  tags: ["figure"],          // stale server snapshot
  auto_tags: ["statue"],
  nsfw: false,
  thumbnail_url: "",
} as unknown as Parameters<typeof MetadataEditor>[0]["model"];

const renderEditor = (currentTags?: string[]) =>
  render(
    <MetadataEditor
      model={baseModel}
      currentTags={currentTags}
      onSaved={vi.fn()}
      onCancel={vi.fn()}
    />
  );

describe("MetadataEditor tag initialization (#299)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("initializes tags from currentTags when provided, not the stale model.tags", () => {
    // Parent promoted "statue" via the + button before the model was refetched.
    renderEditor(["figure", "statue"]);
    expect(screen.getByText("figure")).toBeInTheDocument();
    expect(screen.getByText("statue")).toBeInTheDocument();
  });

  it("falls back to model.tags when currentTags is not supplied", () => {
    renderEditor(undefined);
    expect(screen.getByText("figure")).toBeInTheDocument();
    expect(screen.queryByText("statue")).not.toBeInTheDocument();
  });
});

describe("MetadataEditor inline Fetch applies gallery images too (#1028)", () => {
  beforeEach(() => {
    updateMock.mockClear();
    fetchUrlMock.mockReset();
    applyImagesMock.mockClear();
    toastMock.mockClear();
  });

  const preview = {
    title: "RoboCop Deluxe",
    description: "desc",
    source_url: "https://cults3d.com/x",
    source_site: "cults3d",
    external_id: null,
    creator_name: "CA3D",
    thumbnail_url: "https://cdn/thumb.png",
    image_urls: ["https://cdn/a.png", "https://cdn/b.png"],
    tags: ["figure"],
    category: null,
    license: null,
    like_count: null,
    download_count: null,
  };

  it("queues scraped image_urls on Apply and sends them via applyImages on Save", async () => {
    fetchUrlMock.mockResolvedValue(preview);
    renderEditor();

    fireEvent.change(screen.getByPlaceholderText("https://…"), { target: { value: "https://cults3d.com/x" } });
    fireEvent.click(screen.getByTitle("Fetch metadata from this URL"));
    await waitFor(() => expect(screen.getByText(/2 images found/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(applyImagesMock).toHaveBeenCalledWith(5, ["https://cdn/a.png", "https://cdn/b.png"]),
    );
  });

  it("does not call applyImages when nothing was ever scraped", async () => {
    renderEditor();
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    expect(applyImagesMock).not.toHaveBeenCalled();
  });

  it("a failed applyImages still reports the save as having happened, with a softer message", async () => {
    fetchUrlMock.mockResolvedValue(preview);
    applyImagesMock.mockRejectedValueOnce(new Error("boom"));
    renderEditor();

    fireEvent.change(screen.getByPlaceholderText("https://…"), { target: { value: "https://cults3d.com/x" } });
    fireEvent.click(screen.getByTitle("Fetch metadata from this URL"));
    await waitFor(() => expect(screen.getByText(/2 images found/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("gallery images couldn't be fetched"), "error"),
    );
  });
});
