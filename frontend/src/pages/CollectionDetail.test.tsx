import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CollectionDetail from "./CollectionDetail";

vi.mock("../api/client", async (orig) => {
  const mod = await orig<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      collections: { ...mod.api.collections, list: vi.fn(), getModels: vi.fn(), removeModel: vi.fn() },
    },
  };
});

vi.mock("../components/ModelCard", () => ({ default: () => <div data-testid="model-card" /> }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/collections/3"]}>
      <Routes><Route path="/collections/:id" element={<CollectionDetail />} /></Routes>
    </MemoryRouter>,
  );
}

describe("CollectionDetail loading states", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a skeleton and retries a failed collection load", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.collections.list)
      .mockRejectedValueOnce(new Error("collections unavailable"))
      .mockResolvedValueOnce([{ id: 3, name: "Favorites", description: null, model_count: 0 }] as never);
    vi.mocked(api.collections.getModels).mockResolvedValue([]);

    renderPage();

    expect(screen.getByTestId("collection-loading-skeleton")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("collections unavailable");

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Favorites" })).toBeInTheDocument();
    expect(api.collections.list).toHaveBeenCalledTimes(2);
  });
});
