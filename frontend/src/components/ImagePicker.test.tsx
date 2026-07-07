import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ImagePicker from "./ImagePicker";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(body),
  } as Response);
}

function renderPicker(onApplied = vi.fn(), extra: { modelId?: number; cacheKey?: string } = {}) {
  const utils = render(
    <ImagePicker
      modelId={extra.modelId ?? 7}
      currentPath={null}
      currentUrl={null}
      cacheKey={extra.cacheKey}
      onApplied={onApplied}
      onClose={vi.fn()}
    />
  );
  return { onApplied, ...utils };
}

const imageListCalls = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).startsWith("/api/files/model-images/")).length;

beforeEach(() => {
  fetchMock.mockReset();
  // Mount-time fetch of the model's folder images
  fetchMock.mockImplementation((url: string) => {
    if (url.startsWith("/api/files/model-images/")) return jsonResponse([]);
    return jsonResponse({});
  });
});

describe("ImagePicker – From URL tab", () => {
  it("POSTs to the from-url endpoint and calls onApplied on success", async () => {
    const { onApplied } = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: /from url/i }));
    await userEvent.type(
      screen.getByPlaceholderText("https://…"),
      "https://cdn.example.com/mini.png"
    );

    fetchMock.mockImplementationOnce(() => jsonResponse({ ok: true }));
    await userEvent.click(screen.getByRole("button", { name: /set as thumbnail/i }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/models/7/thumbnail/from-url",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ url: "https://cdn.example.com/mini.png" }),
      })
    );
    expect(onApplied).toHaveBeenCalled();
  });

  it("shows the backend error detail when the download fails", async () => {
    const { onApplied } = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: /from url/i }));
    await userEvent.type(
      screen.getByPlaceholderText("https://…"),
      "https://cdn.example.com/blocked.png"
    );

    fetchMock.mockImplementationOnce(() =>
      jsonResponse({ detail: "Server returned HTTP 403" }, false)
    );
    await userEvent.click(screen.getByRole("button", { name: /set as thumbnail/i }));

    expect(await screen.findByText("Server returned HTTP 403")).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("warns (but keeps the save) when the server falls back to storing the URL", async () => {
    const { onApplied } = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: /from url/i }));
    await userEvent.type(
      screen.getByPlaceholderText("https://…"),
      "https://cdn.example.com/blocked.png"
    );

    // 200 OK but the server couldn't download it (#285 graceful fallback).
    fetchMock.mockImplementationOnce(() =>
      jsonResponse({ ok: true, downloaded: false, detail: "Server returned HTTP 403" })
    );
    await userEvent.click(screen.getByRole("button", { name: /set as thumbnail/i }));

    // Modal stays open with a warning; the parent isn't refreshed until "Done".
    expect(await screen.findByText(/saved as a direct link/i)).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /done/i }));
    expect(onApplied).toHaveBeenCalled();
  });
});

describe("ImagePicker – Upload tab", () => {
  it("uploads the chosen file and calls onApplied on success", async () => {
    const { onApplied } = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    const file = new File(["fake-bytes"], "photo.png", { type: "image/png" });

    fetchMock.mockImplementationOnce(() => jsonResponse({ ok: true, path: "/d/7.png" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/models/7/thumbnail/upload",
      expect.objectContaining({ method: "POST" }),
    );
    expect(onApplied).toHaveBeenCalled();
  });

  it("shows the backend error detail when the upload fails", async () => {
    const { onApplied } = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    const file = new File(["fake-bytes"], "photo.png", { type: "image/png" });

    fetchMock.mockImplementationOnce(() =>
      jsonResponse({ detail: "Image too large (max 15 MB)" }, false)
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);

    expect(await screen.findByText("Image too large (max 15 MB)")).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();
  });
});

describe("ImagePicker – From Folder tab", () => {
  it("re-fetches with ?refresh=true when Refresh is clicked", async () => {
    renderPicker();
    // Wait for the initial empty load so the local-tab content is rendered.
    await screen.findByText(/no images found/i);

    fetchMock.mockImplementationOnce((url: string) => {
      expect(url).toBe("/api/files/model-images/7?refresh=true");
      return jsonResponse([{ path: "/d/new.png", filename: "new.png", url: "/img" }]);
    });
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));

    expect(await screen.findByTitle("new.png")).toBeInTheDocument();
  });
});

describe("ImagePicker – group image-list cache (#303)", () => {
  const oneImage = [{ path: "/d/a.png", filename: "a.png", url: "/img" }];

  it("reuses the cached list for a sibling variant without re-fetching", async () => {
    // Distinct key per test so the module-scope cache can't leak across tests.
    const cacheKey = "9:Akuma";
    fetchMock.mockImplementation((url: string) =>
      url.startsWith("/api/files/model-images/") ? jsonResponse(oneImage) : jsonResponse({}),
    );

    // First variant: fetches and populates the cache.
    const first = renderPicker(vi.fn(), { modelId: 7, cacheKey });
    expect(await screen.findByTitle("a.png")).toBeInTheDocument();
    expect(imageListCalls()).toBe(1);
    first.unmount();

    // Sibling variant (different modelId, same group key): served from cache.
    renderPicker(vi.fn(), { modelId: 8, cacheKey });
    expect(await screen.findByTitle("a.png")).toBeInTheDocument();
    expect(imageListCalls()).toBe(1); // no second folder walk
  });

  it("still re-fetches on Refresh even when the list is cached", async () => {
    const cacheKey = "9:Boomer";
    fetchMock.mockImplementation((url: string) =>
      url.startsWith("/api/files/model-images/") ? jsonResponse(oneImage) : jsonResponse({}),
    );

    renderPicker(vi.fn(), { modelId: 7, cacheKey });
    expect(await screen.findByTitle("a.png")).toBeInTheDocument();
    expect(imageListCalls()).toBe(1);

    fetchMock.mockImplementationOnce((url: string) => {
      expect(url).toBe("/api/files/model-images/7?refresh=true");
      return jsonResponse([{ path: "/d/new.png", filename: "new.png", url: "/img" }]);
    });
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));

    expect(await screen.findByTitle("new.png")).toBeInTheDocument();
    expect(imageListCalls()).toBe(2);
  });

  it("always fetches when no cacheKey is given", async () => {
    fetchMock.mockImplementation((url: string) =>
      url.startsWith("/api/files/model-images/") ? jsonResponse(oneImage) : jsonResponse({}),
    );

    const first = renderPicker(vi.fn(), { modelId: 7 });
    expect(await screen.findByTitle("a.png")).toBeInTheDocument();
    first.unmount();

    renderPicker(vi.fn(), { modelId: 7 });
    expect(await screen.findByTitle("a.png")).toBeInTheDocument();
    expect(imageListCalls()).toBe(2); // no caching without a key
  });
});
