import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TagsPage from "./TagsPage";

const TAGS = [
  { tag: "figure", count: 12 },
  { tag: "bust", count: 7 },
  { tag: "statue", count: 3 },
];

vi.mock("../api/client", () => ({
  api: {
    models: {
      tags: vi.fn(async () => TAGS),
      renameTag: vi.fn(async () => ({ ok: true, updated: 3 })),
      mergeTag: vi.fn(async () => ({ ok: true, updated: 5 })),
      deleteTag: vi.fn(async () => ({ ok: true, updated: 2 })),
    },
  },
}));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("../components/HelpLink", () => ({ default: () => null }));

import { api } from "../api/client";

const renderPage = () => render(<MemoryRouter><TagsPage /></MemoryRouter>);

describe("TagsPage (#165)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the shared error state on load failure, with a working Retry", async () => {
    vi.mocked(api.models.tags).mockRejectedValueOnce(new Error("Server unreachable"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Server unreachable");
    expect(screen.getByText("Couldn't load tags")).toBeInTheDocument();

    vi.mocked(api.models.tags).mockResolvedValueOnce(TAGS);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.getByText("figure")).toBeInTheDocument());
  });

  it("shows the loading skeleton while pending, then swaps to real content", async () => {
    let resolveTags!: (v: typeof TAGS) => void;
    vi.mocked(api.models.tags).mockReturnValueOnce(new Promise((resolve) => { resolveTags = resolve; }));
    renderPage();

    expect(screen.getByTestId("tags-loading-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("figure")).toBeNull();

    resolveTags(TAGS);
    await waitFor(() => expect(screen.getByText("figure")).toBeInTheDocument());
    expect(screen.queryByTestId("tags-loading-skeleton")).toBeNull();
  });

  it("loads and displays tags with counts", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("figure")).toBeInTheDocument());
    expect(screen.getByText("bust")).toBeInTheDocument();
    expect(screen.getByText("statue")).toBeInTheDocument();
    expect(screen.getByText("12 models")).toBeInTheDocument();
    expect(screen.getByText("7 models")).toBeInTheDocument();
  });

  it("filters tags by search input", async () => {
    renderPage();
    await waitFor(() => screen.getByText("figure"));
    fireEvent.change(screen.getByPlaceholderText("Filter tags…"), { target: { value: "bu" } });
    expect(screen.getByText("bust")).toBeInTheDocument();
    expect(screen.queryByText("figure")).toBeNull();
    expect(screen.queryByText("statue")).toBeNull();
  });

  it("opens rename form and submits", async () => {
    renderPage();
    await waitFor(() => screen.getByText("figure"));
    fireEvent.click(screen.getByRole("button", { name: /rename tag figure/i }));
    const input = screen.getByPlaceholderText("New tag name…");
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "miniature" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm rename/i }));
    await waitFor(() => expect(vi.mocked(api.models.renameTag)).toHaveBeenCalledWith("figure", "miniature"));
  });

  it("cancels rename on Escape", async () => {
    renderPage();
    await waitFor(() => screen.getByText("figure"));
    fireEvent.click(screen.getByRole("button", { name: /rename tag figure/i }));
    const input = screen.getByPlaceholderText("New tag name…");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByPlaceholderText("New tag name…")).toBeNull();
  });

  it("opens merge dropdown", async () => {
    renderPage();
    await waitFor(() => screen.getByText("figure"));
    fireEvent.click(screen.getByRole("button", { name: /merge tag figure/i }));
    expect(screen.getByText("Merge into…")).toBeInTheDocument();
    // bust and statue should be in the dropdown (not figure itself)
    expect(screen.getByRole("option", { name: /bust/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /figure/ })).toBeNull();
  });

  it("submits merge and calls api.models.mergeTag", async () => {
    renderPage();
    await waitFor(() => screen.getByText("figure"));
    fireEvent.click(screen.getByRole("button", { name: /merge tag figure/i }));
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "bust" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm merge/i }));
    await waitFor(() => expect(vi.mocked(api.models.mergeTag)).toHaveBeenCalledWith("figure", "bust"));
  });

  it("calls api.models.deleteTag after confirm", async () => {
    renderPage();
    await waitFor(() => screen.getByText("figure"));
    fireEvent.click(screen.getByRole("button", { name: /delete tag figure/i }));
    await waitFor(() => expect(vi.mocked(api.models.deleteTag)).toHaveBeenCalledWith("figure"));
  });
});
