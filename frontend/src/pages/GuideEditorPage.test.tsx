import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import GuideEditorPage from "./GuideEditorPage";
import { ApiError } from "../api/client";

const navigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const orig = await importOriginal<typeof import("react-router-dom")>();
  return { ...orig, useNavigate: () => navigate };
});

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: { painting: { guides: { get: vi.fn(), create: vi.fn(), update: vi.fn() } } },
  };
});

const toast = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast }) }));

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/painting/guides/new" element={<GuideEditorPage />} />
        <Route path="/painting/guides/:id/edit" element={<GuideEditorPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("GuideEditorPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("creates a guide and navigates to the reader", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.create).mockResolvedValue({ id: 42 } as never);

    renderAt("/painting/guides/new");
    await userEvent.type(screen.getByLabelText("Title *"), "RoboCop");
    await userEvent.click(screen.getByRole("button", { name: "Create guide" }));

    await waitFor(() => expect(api.painting.guides.create).toHaveBeenCalled());
    expect(navigate).toHaveBeenCalledWith("/painting/guides/42");
  });

  it("surfaces a 409 slug conflict inline without navigating", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.create).mockRejectedValue(new ApiError(409, "Conflict"));

    renderAt("/painting/guides/new");
    await userEvent.type(screen.getByLabelText("Title *"), "RoboCop");
    await userEvent.click(screen.getByRole("button", { name: "Create guide" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/slug is already taken/i);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("loads an existing guide and saves metadata without the tabs spine", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.get).mockResolvedValue({
      id: 5, slug: "robocop", title: "RoboCop", franchise: null, technique_tags: [], paint_lines_used: [],
    } as never);
    vi.mocked(api.painting.guides.update).mockResolvedValue({ id: 5 } as never);

    renderAt("/painting/guides/5/edit");
    expect(await screen.findByDisplayValue("RoboCop")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api.painting.guides.update).toHaveBeenCalled());
    const [, patch] = vi.mocked(api.painting.guides.update).mock.calls[0];
    expect(patch).not.toHaveProperty("tabs");
    expect(navigate).toHaveBeenCalledWith("/painting/guides/5");
  });

  it("shows a loading skeleton and retries a failed guide load", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.get)
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce({
        id: 5, slug: "robocop", title: "RoboCop", franchise: null, technique_tags: [], paint_lines_used: [],
      } as never);

    renderAt("/painting/guides/5/edit");
    expect(screen.getByTestId("guide-editor-loading-skeleton")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("network unavailable");

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByDisplayValue("RoboCop")).toBeInTheDocument();
    expect(api.painting.guides.get).toHaveBeenCalledTimes(2);
  });
});
