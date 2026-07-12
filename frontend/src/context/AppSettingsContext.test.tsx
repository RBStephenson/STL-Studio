import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { AppSettingsProvider, useAppSettings } from "./AppSettingsContext";
import { mkSettings } from "../test/settings";

vi.mock("../api/client", () => ({
  api: { settings: { get: vi.fn(), update: vi.fn(), upsertPreset: vi.fn(), deletePreset: vi.fn() } },
}));
vi.mock("../utils/legacyPreferences", () => ({
  collectLegacyPreferences: () => ({}),
  clearLegacyPreferences: () => {},
}));

const toastMock = vi.fn();
vi.mock("./ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

import { api } from "../api/client";

function Probe() {
  const { loaded, loadError, settings } = useAppSettings();
  return (
    <div>
      <span data-testid="loaded">{String(loaded)}</span>
      <span data-testid="error">{String(loadError)}</span>
      <span data-testid="page-size">{settings.library_page_size}</span>
    </div>
  );
}

function ToggleProbe() {
  const { settings, update } = useAppSettings();
  return (
    <div>
      <span data-testid="auto-rotate">{String(settings.gallery_auto_rotate)}</span>
      <button
        onClick={() => {
          update({ gallery_auto_rotate: !settings.gallery_auto_rotate }).catch(() => {});
        }}
      >
        Toggle
      </button>
    </div>
  );
}

describe("AppSettingsProvider load-error surfacing (STUDIO-96)", () => {
  afterEach(() => { vi.clearAllMocks(); });

  it("marks loaded with no error and server-confirmed settings on success", async () => {
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ library_page_size: 96 }));

    render(<AppSettingsProvider><Probe /></AppSettingsProvider>);

    await waitFor(() => expect(screen.getByTestId("loaded")).toHaveTextContent("true"));
    expect(screen.getByTestId("error")).toHaveTextContent("false");
    expect(screen.getByTestId("page-size")).toHaveTextContent("96");
    expect(toastMock).not.toHaveBeenCalled();
  });

  it("exposes an error state and surfaces a toast when the load fails, without crashing on the fallback defaults", async () => {
    vi.mocked(api.settings.get).mockRejectedValue(new Error("network down"));

    render(<AppSettingsProvider><Probe /></AppSettingsProvider>);

    await waitFor(() => expect(screen.getByTestId("loaded")).toHaveTextContent("true"));
    expect(screen.getByTestId("error")).toHaveTextContent("true");
    // Hardcoded fallback, not server-confirmed — still usable, just flagged.
    expect(screen.getByTestId("page-size")).toHaveTextContent("50");
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("Couldn't load settings"), "error");
  });
});

describe("AppSettingsProvider optimistic update (STUDIO-180)", () => {
  afterEach(() => { vi.clearAllMocks(); });

  it("flips the setting immediately, before the PATCH resolves", async () => {
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ gallery_auto_rotate: false }));
    let resolveUpdate: (v: Awaited<ReturnType<typeof api.settings.update>>) => void;
    vi.mocked(api.settings.update).mockReturnValue(
      new Promise((resolve) => { resolveUpdate = resolve; }),
    );

    render(<AppSettingsProvider><ToggleProbe /></AppSettingsProvider>);
    await waitFor(() => expect(screen.getByTestId("auto-rotate")).toHaveTextContent("false"));

    fireEvent.click(screen.getByRole("button", { name: "Toggle" }));

    // Flips before the PATCH has resolved — no round-trip wait.
    expect(screen.getByTestId("auto-rotate")).toHaveTextContent("true");

    resolveUpdate!(mkSettings({ gallery_auto_rotate: true }));
    await waitFor(() => expect(screen.getByTestId("auto-rotate")).toHaveTextContent("true"));
  });

  it("rolls back to the prior value if the PATCH fails, and rethrows for the caller", async () => {
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ gallery_auto_rotate: false }));
    vi.mocked(api.settings.update).mockRejectedValue(new Error("db locked"));

    render(<AppSettingsProvider><ToggleProbe /></AppSettingsProvider>);
    await waitFor(() => expect(screen.getByTestId("auto-rotate")).toHaveTextContent("false"));

    fireEvent.click(screen.getByRole("button", { name: "Toggle" }));
    expect(screen.getByTestId("auto-rotate")).toHaveTextContent("true");

    // Rolled back once the rejected PATCH resolves — the caller (ToggleProbe's
    // onClick) is the one that would surface the error, same as every real
    // settings tab does via its own flash banner.
    await waitFor(() => expect(screen.getByTestId("auto-rotate")).toHaveTextContent("false"));
  });
});
