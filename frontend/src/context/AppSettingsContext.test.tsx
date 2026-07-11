import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
