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
});
