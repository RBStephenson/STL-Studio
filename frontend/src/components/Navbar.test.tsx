import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Navbar from "./Navbar";
import { AppSettingsProvider } from "../context/AppSettingsContext";
import { mkSettings } from "../test/settings";

vi.mock("../api/client", () => ({
  api: {
    models: {
      stats: vi.fn().mockResolvedValue({ needs_review: 0, queued: 0 }),
    },
    settings: {
      get: vi.fn().mockResolvedValue({
        painting_guides_enabled: false,
        show_nsfw: false,
        library_page_size: 48,
        filter_presets: [],
        recent_days: 7,
      }),
      update: vi.fn(),
    },
  },
}));

function renderNavbar() {
  return render(
    <MemoryRouter>
      <AppSettingsProvider>
        <Navbar />
      </AppSettingsProvider>
    </MemoryRouter>
  );
}

describe("Navbar – painting nav gating (#180/#181)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("hides Guides but keeps Paint Shelf when painting guides are disabled (#516)", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: false }));

    renderNavbar();

    // Wait for the settings fetch to settle, then assert. Paint Shelf is
    // standalone inventory — always shown; only Guides gates on the flag.
    expect(await screen.findByText("Paint Shelf")).toBeInTheDocument();
    expect(screen.queryByText("Guides")).toBeNull();
    expect(screen.getByText("Paint Shelf").closest("a")).toHaveAttribute("href", "/painting/shelf");
  });

  it("shows Guides and Paint Shelf when painting guides are enabled", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: true }));

    renderNavbar();

    expect(await screen.findByText("Guides")).toBeInTheDocument();
    expect(screen.getByText("Paint Shelf")).toBeInTheDocument();
    expect(screen.getByText("Guides").closest("a")).toHaveAttribute("href", "/painting/guides");
    expect(screen.getByText("Paint Shelf").closest("a")).toHaveAttribute("href", "/painting/shelf");
  });
});

describe("Navbar – NSFW toggle persists server-side (#32)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("reflects the server value and PATCHes the flip", async () => {
    const { api } = await import("../api/client");
    const userEvent = (await import("@testing-library/user-event")).default;
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ show_nsfw: false }));
    vi.mocked(api.settings.update).mockResolvedValue(mkSettings({ show_nsfw: true }));

    renderNavbar();

    const btn = await screen.findByRole("button", { name: /nsfw off/i });
    await userEvent.click(btn);

    expect(api.settings.update).toHaveBeenCalledWith({ show_nsfw: true });
    expect(await screen.findByRole("button", { name: /nsfw on/i })).toBeInTheDocument();
  });
});
