import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AiIntegrationsTab from "./AiIntegrationsTab";
import { AppSettingsProvider } from "../../context/AppSettingsContext";
import { mkSettings } from "../../test/settings";

vi.mock("../../api/client", () => ({
  api: {
    settings: {
      get: vi.fn().mockResolvedValue({
        painting_guides_enabled: true,
        ai_model: "claude-sonnet-4-6",
        ai_effort: "low",
      }),
      update: vi.fn().mockResolvedValue({}),
      ai: {
        get: vi.fn().mockResolvedValue({ key_set: false, key_hint: null, model: "", effort: "low" }),
        setKey: vi.fn(),
        clearKey: vi.fn(),
      },
      cults: {
        get: vi.fn().mockResolvedValue({ credentials_set: false, hint: null }),
        setCredentials: vi.fn(),
        clearCredentials: vi.fn(),
      },
      mmf: {
        get: vi.fn().mockResolvedValue({ key_set: false, key_hint: null }),
        setKey: vi.fn().mockResolvedValue({ key_set: true, key_hint: "…wxyz" }),
        clearKey: vi.fn().mockResolvedValue({ key_set: false, key_hint: null }),
      },
    },
  },
}));

const renderTab = () =>
  render(<AppSettingsProvider><AiIntegrationsTab /></AppSettingsProvider>);

// The MMF input + its Save live in one container — scope to it so the
// Anthropic and Cults Save buttons don't collide.
const mmfSave = (input: HTMLElement) =>
  within(input.closest("div")!).getByRole("button", { name: "Save" });

describe("AiIntegrationsTab – MyMiniFactory key", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the MMF key field", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: true }));

    renderTab();

    expect(await screen.findByLabelText("MyMiniFactory API key")).toBeInTheDocument();
    expect(api.settings.mmf.get).toHaveBeenCalled();
  });

  it("saves a typed key and shows the masked, key-set state", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: true }));

    renderTab();

    const input = await screen.findByLabelText("MyMiniFactory API key");
    await userEvent.type(input, "ff53-secret-wxyz");
    await userEvent.click(mmfSave(input));

    expect(api.settings.mmf.setKey).toHaveBeenCalledWith("ff53-secret-wxyz");
    expect(await screen.findByText(/key set/i)).toBeInTheDocument();
    expect(screen.getByText(/wxyz/)).toBeInTheDocument();
  });

  it("shows the key-set state on load and clears the key", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.settings.get).mockResolvedValue(mkSettings({ painting_guides_enabled: true }));
    vi.mocked(api.settings.mmf.get).mockResolvedValue({ key_set: true, key_hint: "…wxyz" });

    renderTab();

    // "Key set" appears for the MMF section (Anthropic stays unset in this test).
    expect(await screen.findByText(/key set/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(api.settings.mmf.clearKey).toHaveBeenCalled();
  });
});
