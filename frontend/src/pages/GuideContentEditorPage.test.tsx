import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import GuideContentEditorPage from "./GuideContentEditorPage";

vi.mock("react-router-dom", async (orig) => {
  const mod = await orig<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => vi.fn(), useParams: () => ({ id: "7" }) };
});

vi.mock("../api/client", async (orig) => {
  const mod = await orig<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      painting: {
        ...mod.api.painting,
        guides: { ...mod.api.painting.guides, get: vi.fn(), validate: vi.fn(), update: vi.fn() },
      },
    },
  };
});

vi.mock("../components/guide/GuideSpineEditor", () => ({ default: () => <div data-testid="spine-editor" /> }));
vi.mock("../components/guide/GuideReader", () => ({ default: () => <div data-testid="guide-reader" /> }));
vi.mock("../components/guide/GuideValidationPanel", () => ({ default: () => <div data-testid="validation" /> }));
vi.mock("../components/guide/ReferenceImageUpload", () => ({ default: () => <div data-testid="reference-upload" /> }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

describe("GuideContentEditorPage loading states", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a skeleton and retries a failed guide load", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.painting.guides.get)
      .mockRejectedValueOnce(new Error("guide service unavailable"))
      .mockResolvedValueOnce({ id: 7, title: "RoboCop", tabs: [], reference_image_id: null } as never);
    vi.mocked(api.painting.guides.validate).mockResolvedValue({ ok: true, flags: [] } as never);

    render(<MemoryRouter><GuideContentEditorPage /></MemoryRouter>);

    expect(screen.getByTestId("guide-content-loading-skeleton")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("guide service unavailable");

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByTestId("spine-editor")).toBeInTheDocument();
    expect(api.painting.guides.get).toHaveBeenCalledTimes(2);
  });
});
