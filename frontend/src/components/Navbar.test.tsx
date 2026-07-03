import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
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

describe("Navbar – badge counts stay fresh (#543)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the queue count and refetches it on window focus", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.stats).mockResolvedValue({ needs_review: 0, queued: 7 } as any);

    renderNavbar();
    expect(await screen.findByText("7")).toBeInTheDocument();

    // An item leaves the queue elsewhere; on focus the badge refreshes.
    vi.mocked(api.models.stats).mockResolvedValue({ needs_review: 0, queued: 6 } as any);
    fireEvent(window, new Event("focus"));
    expect(await screen.findByText("6")).toBeInTheDocument();
  });

  it("refreshes the review badge on a short poll without a route change or focus (STUDIO-6)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = await import("../api/client");
    vi.mocked(api.models.stats).mockResolvedValue({ needs_review: 2, queued: 0 } as any);

    renderNavbar();
    expect(await screen.findByText("2")).toBeInTheDocument();

    // Something on the same page (e.g. bulk enrich) flags a new item for
    // review, with no route change and no window blur/refocus.
    vi.mocked(api.models.stats).mockResolvedValue({ needs_review: 3, queued: 0 } as any);
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(await screen.findByText("3")).toBeInTheDocument();

    vi.useRealTimers();
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
