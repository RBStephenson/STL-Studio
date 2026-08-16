import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InstallPage from "./InstallPage";

const LIBRARIES = vi.hoisted(() => [
  { id: 1, name: "Main Library", path: "/library", is_writable: true, write_enabled: true },
  { id: 2, name: "Read-only Archive", path: "/archive", is_writable: false, write_enabled: false },
]);
const CREATORS = vi.hoisted(() => [
  { id: 10, name: "Abe3D", source_url: null, model_count: 3 },
]);

const browseMock = vi.fn();
const librariesMock = vi.fn();
const creatorsMock = vi.fn();
const installMock = vi.fn();
const startCreatorMock = vi.fn();
const statusMock = vi.fn();

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return {
    ...orig,
    api: {
      scan: {
        browse: (...args: unknown[]) => browseMock(...args),
        libraries: () => librariesMock(),
        startCreator: (id: number) => startCreatorMock(id),
        status: () => statusMock(),
      },
      models: {
        creators: () => creatorsMock(),
      },
      import: {
        install: (...args: unknown[]) => installMock(...args),
      },
    },
  };
});

describe("InstallPage (STUDIO-389)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    librariesMock.mockResolvedValue(LIBRARIES);
    creatorsMock.mockResolvedValue(CREATORS);
    browseMock.mockResolvedValue({
      path: "/library/Abe3D", parent: "/library", is_drive_list: false,
      entries: [{ name: "zarana.zip", path: "/library/Abe3D/zarana.zip", is_dir: false }],
    });
    startCreatorMock.mockResolvedValue({ running: true, message: "scanning" });
    statusMock.mockResolvedValue({ running: false, message: "done" });
  });

  it("only offers writable libraries in the destination dropdown", async () => {
    render(<InstallPage />);
    await waitFor(() => expect(librariesMock).toHaveBeenCalled());

    expect(await screen.findByText(/Main Library/)).toBeInTheDocument();
    expect(screen.queryByText(/Read-only Archive/)).toBeNull();
  });

  it("builds a live destination preview from library + creator + character", async () => {
    render(<InstallPage />);
    await waitFor(() => expect(creatorsMock).toHaveBeenCalled());

    await userEvent.selectOptions(await screen.findByLabelText(/library/i), "1");
    await userEvent.selectOptions(screen.getByLabelText(/creator/i), "10");
    await userEvent.type(screen.getByPlaceholderText(/zarana/i), "Cobra Commander");

    expect(await screen.findByText("/library/Abe3D/Cobra Commander")).toBeInTheDocument();
  });

  it("disables Install until source, library, creator, and character are all set", async () => {
    render(<InstallPage />);
    await waitFor(() => expect(creatorsMock).toHaveBeenCalled());

    expect(screen.getByRole("button", { name: /^install$/i })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /browse/i }));
    await userEvent.click(await screen.findByText("zarana.zip"));
    await userEvent.selectOptions(screen.getByLabelText(/library/i), "1");
    await userEvent.selectOptions(screen.getByLabelText(/creator/i), "10");
    await userEvent.type(screen.getByPlaceholderText(/zarana/i), "Cobra Commander");

    expect(screen.getByRole("button", { name: /^install$/i })).toBeEnabled();
  });

  it("switching to 'New' creator clears the dropdown selection and uses the typed name", async () => {
    installMock.mockResolvedValue({
      dest: "/library/3DMOONN/Percy", creator_id: 99, creator: "3DMOONN",
      file_count: 5, total_bytes: 12345,
    });

    render(<InstallPage />);
    await waitFor(() => expect(creatorsMock).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /browse/i }));
    await userEvent.click(await screen.findByText("zarana.zip"));
    await userEvent.selectOptions(screen.getByLabelText(/library/i), "1");
    await userEvent.click(screen.getByRole("button", { name: /new/i }));
    await userEvent.type(screen.getByPlaceholderText(/new creator name/i), "3DMOONN");
    await userEvent.type(screen.getByPlaceholderText(/zarana/i), "Percy");

    await userEvent.click(screen.getByRole("button", { name: /^install$/i }));

    await waitFor(() =>
      expect(installMock).toHaveBeenCalledWith(
        "/library/Abe3D/zarana.zip", 1, "3DMOONN", "Percy",
      )
    );
  });

  it("shows the install result and a separate, not-auto-chained Scan now action", async () => {
    installMock.mockResolvedValue({
      dest: "/library/Abe3D/Cobra Commander", creator_id: 10, creator: "Abe3D",
      file_count: 4, total_bytes: 2048,
    });
    startCreatorMock.mockResolvedValue({ running: true, message: "scanning Abe3D" });
    statusMock.mockResolvedValue({ running: false, message: "done" });

    render(<InstallPage />);
    await waitFor(() => expect(creatorsMock).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /browse/i }));
    await userEvent.click(await screen.findByText("zarana.zip"));
    await userEvent.selectOptions(screen.getByLabelText(/library/i), "1");
    await userEvent.selectOptions(screen.getByLabelText(/creator/i), "10");
    await userEvent.type(screen.getByPlaceholderText(/zarana/i), "Cobra Commander");
    await userEvent.click(screen.getByRole("button", { name: /^install$/i }));

    expect(await screen.findByText(/installed 4 files/i)).toBeInTheDocument();
    // The scan is a distinct, user-triggered step — not fired automatically.
    expect(startCreatorMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /scan now/i }));
    await waitFor(() => expect(startCreatorMock).toHaveBeenCalledWith(10));
  });

  it("shows an error and lets the user retry when install fails", async () => {
    installMock.mockRejectedValue(new Error("destination already exists"));

    render(<InstallPage />);
    await waitFor(() => expect(creatorsMock).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /browse/i }));
    await userEvent.click(await screen.findByText("zarana.zip"));
    await userEvent.selectOptions(screen.getByLabelText(/library/i), "1");
    await userEvent.selectOptions(screen.getByLabelText(/creator/i), "10");
    await userEvent.type(screen.getByPlaceholderText(/zarana/i), "Cobra Commander");
    await userEvent.click(screen.getByRole("button", { name: /^install$/i }));

    expect(await screen.findByText("destination already exists")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByRole("button", { name: /^install$/i })).toBeInTheDocument();
  });
});
