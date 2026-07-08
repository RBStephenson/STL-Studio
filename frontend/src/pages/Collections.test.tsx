import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
