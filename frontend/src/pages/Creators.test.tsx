import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Creators from "./Creators";

const CREATORS = [
  { id: 1, name: "Toon Studios", source_url: null, model_count: 12 },
];

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      ...orig.api,
      models: {
        ...orig.api.models,
        creators: vi.fn(async () => CREATORS),
      },
    },
  };
});
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/RefreshEnrich", () => ({ default: () => null }));

function renderPage() {
  return render(<MemoryRouter><Creators /></MemoryRouter>);
}

describe("Creators error state", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the shared error state on load failure, with a working Retry", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockRejectedValueOnce(new Error("Backend unreachable"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unreachable");
    expect(screen.getByText("Couldn't load creators")).toBeInTheDocument();

    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Toon Studios")).toBeInTheDocument();
  });

  it("shows the empty state when a search matches no creators", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    renderPage();

    await screen.findByText("Toon Studios");
    await userEvent.type(screen.getByPlaceholderText("Search creators…"), "nonexistent");

    expect(screen.getByText("No creators found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add creator/ })).toBeInTheDocument();
  });
});

describe("Creators Library Tools menu (STUDIO-155)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("hides Reorganize Library in the menu when the flag is off, shows Rescan All Folders regardless", async () => {
    vi.resetModules();
    vi.doMock("../context/AppSettingsContext", () => ({
      useAppSettings: () => ({ settings: { reorganize_enabled: false } }),
    }));
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    const CreatorsFlagOff = (await import("./Creators")).default;
    render(<MemoryRouter><CreatorsFlagOff /></MemoryRouter>);

    await screen.findByText("Toon Studios");
    await userEvent.click(screen.getByRole("button", { name: /Library Tools/i }));

    expect(screen.queryByRole("button", { name: /Reorganize Library/i })).toBeNull();
    expect(screen.getByRole("button", { name: /Rescan All Folders/i })).toBeInTheDocument();
    vi.doUnmock("../context/AppSettingsContext");
  });

  it("shows Reorganize Library in the menu when the flag is on and navigates to /reorganize", async () => {
    vi.resetModules();
    vi.doMock("../context/AppSettingsContext", () => ({
      useAppSettings: () => ({ settings: { reorganize_enabled: true } }),
    }));
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    const CreatorsFlagOn = (await import("./Creators")).default;
    render(<MemoryRouter><CreatorsFlagOn /></MemoryRouter>);

    await screen.findByText("Toon Studios");
    await userEvent.click(screen.getByRole("button", { name: /Library Tools/i }));
    const reorgItem = screen.getByRole("button", { name: /Reorganize Library/i });
    expect(reorgItem).toBeInTheDocument();
    await userEvent.click(reorgItem);
    // Menu closes after navigating.
    expect(screen.queryByRole("button", { name: /Rescan All Folders/i })).toBeNull();
    vi.doUnmock("../context/AppSettingsContext");
  });
});
