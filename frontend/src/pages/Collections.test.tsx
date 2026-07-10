import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

const mockState = vi.hoisted(() => ({
  settings: { collections_uniform_size: true },
}));

vi.mock("../api/client", () => ({
  api: {
    fileUrl: (p: string) => p,
    collections: {
      list: vi.fn(async () => [
        { id: 1, name: "With Cover", description: null, cover_image_path: "cover.jpg", model_count: 2, created_at: "" },
        { id: 2, name: "No Cover", description: null, cover_image_path: null, model_count: 0, created_at: "" },
      ]),
    },
  },
}));
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: mockState.settings }),
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import Collections from "./Collections";

const renderPage = () => render(<MemoryRouter><Collections /></MemoryRouter>);

describe("Collections error state", () => {
  it("shows the shared error state on load failure, with a working Retry", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.collections.list).mockRejectedValueOnce(new Error("Server unreachable"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Server unreachable");
    expect(screen.getByText("Couldn't load collections")).toBeInTheDocument();

    vi.mocked(api.collections.list).mockResolvedValueOnce([
      { id: 1, name: "With Cover", description: null, cover_image_path: "cover.jpg", model_count: 2, created_at: "" },
    ]);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByRole("link", { name: /With Cover/ })).toBeInTheDocument();
  });
});

describe("Collections card sizing", () => {
  it("gives a no-cover collection the same big box as a cover one when uniform size is on", async () => {
    mockState.settings.collections_uniform_size = true;
    renderPage();

    const noCover = await screen.findByRole("link", { name: /No Cover/ });
    const withCover = screen.getByRole("link", { name: /With Cover/ });
    expect(noCover.className).toContain("aspect-[4/3]");
    expect(withCover.className).toContain("aspect-[4/3]");
  });

  it("keeps a no-cover collection compact when uniform size is off, but a cover always stays big", async () => {
    mockState.settings.collections_uniform_size = false;
    renderPage();

    const noCover = await screen.findByRole("link", { name: /No Cover/ });
    const withCover = screen.getByRole("link", { name: /With Cover/ });
    expect(noCover.className).not.toContain("aspect-[4/3]");
    expect(withCover.className).toContain("aspect-[4/3]");
  });
});
