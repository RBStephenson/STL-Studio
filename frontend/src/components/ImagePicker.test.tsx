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

function renderPicker(onApplied = vi.fn()) {
  render(
    <ImagePicker
      modelId={7}
      currentPath={null}
      currentUrl={null}
      onApplied={onApplied}
      onClose={vi.fn()}
    />
  );
  return onApplied;
}

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
    const onApplied = renderPicker();

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
    const onApplied = renderPicker();

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
});
