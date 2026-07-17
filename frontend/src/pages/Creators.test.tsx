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
        deleteCreator: vi.fn(async () => undefined),
      },
    },
  };
});
const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("../components/RefreshEnrich", () => ({ default: () => null }));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));

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

describe("Creators delete", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("deletes the creator after confirming and removes its card", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    renderPage();
    await screen.findByText("Toon Studios");

    await userEvent.click(screen.getByRole("button", { name: /Delete Toon Studios/i }));

    expect(api.models.deleteCreator).toHaveBeenCalledWith(1);
    await screen.findByText("No creators found");
    expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("deleted"), "success");
  });

  it("surfaces the server's blocked-deletion message instead of deleting", async () => {
    const { api, ApiError } = await import("../api/client");
    vi.mocked(api.models.creators).mockResolvedValueOnce(CREATORS);
    vi.mocked(api.models.deleteCreator).mockRejectedValueOnce(
      new ApiError(409, 'Can\'t delete "Toon Studios" — it still has 12 models. Move or delete those first.'),
    );
    renderPage();
    await screen.findByText("Toon Studios");

    await userEvent.click(screen.getByRole("button", { name: /Delete Toon Studios/i }));

    await vi.waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(expect.stringContaining("still has 12 models"), "error");
    });
    // Not removed — the card is still there since deletion was blocked.
    expect(screen.getByText("Toon Studios")).toBeInTheDocument();
  });
});
