import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import GuideWizardPage from "./GuideWizardPage";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (orig) => {
  const mod = await orig<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => mockNavigate };
});

// vi.mock is hoisted — can't reference a let/const declared outside the factory.
// Use vi.fn() inline; swap implementation in beforeEach.
vi.mock("../api/client", async (orig) => {
  const mod = await orig<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      painting: {
        ...mod.api.painting,
        guides: {
          ...mod.api.painting.guides,
          create: vi.fn().mockResolvedValue({ id: 42 }),
        },
      },
      models: { list: vi.fn().mockResolvedValue({ items: [] }) },
    },
  };
});

vi.mock("../context/ToastContext", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

function renderWizard() {
  return render(
    <MemoryRouter>
      <GuideWizardPage />
    </MemoryRouter>,
  );
}

// Helper to grab the mocked create fn after the module is loaded.
async function getCreateMock() {
  const { api } = await import("../api/client");
  return vi.mocked(api.painting.guides.create);
}

describe("GuideWizardPage (#487)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders step 1 with title input", () => {
    renderWizard();
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(screen.getByLabelText(/title \*/i)).toBeInTheDocument();
  });

  it("blocks advance from step 1 when title is empty", async () => {
    renderWizard();
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/title is required/i);
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
  });

  it("advances step 1→2 after typing a title", async () => {
    renderWizard();
    await userEvent.type(screen.getByLabelText(/title \*/i), "Presto Guide");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("Step 2 of 3")).toBeInTheDocument();
    expect(screen.getByLabelText("Search models")).toBeInTheDocument();
  });

  it("Back button returns to step 1 from step 2", async () => {
    renderWizard();
    await userEvent.type(screen.getByLabelText(/title \*/i), "A Guide");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
  });

  it("advances step 2→3: AI-draft checkbox enabled, reference-images still disabled", async () => {
    renderWizard();
    await userEvent.type(screen.getByLabelText(/title \*/i), "My Guide");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("Step 3 of 3")).toBeInTheDocument();
    expect(screen.getByText("My Guide")).toBeInTheDocument();
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toBeEnabled();   // Generate AI draft
    expect(checkboxes[1]).toBeDisabled();  // Generate reference images (#536/#494)
  });

  it("routes to the draft review page when 'Generate AI draft' is checked", async () => {
    const create = await getCreateMock();
    create.mockResolvedValue({ id: 42 } as never);
    renderWizard();

    await userEvent.type(screen.getByLabelText(/title \*/i), "Draft Guide");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /generate ai draft/i }));
    await userEvent.click(screen.getByRole("button", { name: /create guide/i }));

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/painting/guides/42/draft"));
  });

  it("creates guide with correct payload and navigates to content editor", async () => {
    const create = await getCreateMock();
    create.mockResolvedValue({ id: 42 } as never);
    renderWizard();

    await userEvent.type(screen.getByLabelText(/title \*/i), "Test Guide");
    await userEvent.selectOptions(screen.getByLabelText(/scale/i), "75mm");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /create guide/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(create.mock.calls[0][0]).toMatchObject({
      title: "Test Guide",
      slug: "test-guide",
      scale: "75mm",
      status: "draft",
    });
    expect(mockNavigate).toHaveBeenCalledWith("/painting/guides/42/content");
  });

  it("shows API error on step 3 without navigating away", async () => {
    const create = await getCreateMock();
    create.mockRejectedValue(new Error("Server blew up") as never);
    renderWizard();

    await userEvent.type(screen.getByLabelText(/title \*/i), "Bad Guide");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /create guide/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Server blew up"),
    );
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByText("Step 3 of 3")).toBeInTheDocument();
  });
});
