import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Settings from "./Settings";

vi.mock("../api/client", () => ({
  api: {
    scan: {
      roots: vi.fn().mockResolvedValue([]),
      addRoot: vi.fn().mockResolvedValue({}),
    },
  },
}));

vi.mock("../components/FolderPicker", () => ({
  default: ({ onSelect, onClose }: { onSelect: (p: string) => void; onClose: () => void }) => (
    <div data-testid="folder-picker">
      <button onClick={() => onSelect("/picked/path")}>Select folder</button>
      <button onClick={onClose}>Close picker</button>
    </div>
  ),
}));

vi.mock("../components/HelpLink", () => ({ default: () => null }));

describe("Settings – Add Folder button", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("opens FolderPicker when clicked with an empty path field", async () => {
    render(<Settings />);
    expect(screen.queryByTestId("folder-picker")).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(screen.getByTestId("folder-picker")).toBeInTheDocument();
  });

  it("calls api.scan.addRoot directly when path field already has a value", async () => {
    const { api } = await import("../api/client");
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/my/models");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(api.scan.addRoot).toHaveBeenCalledWith("/my/models", "{creator}");
    expect(screen.queryByTestId("folder-picker")).toBeNull();
  });

  it("adds the folder selected via FolderPicker and closes the picker", async () => {
    const { api } = await import("../api/client");
    render(<Settings />);

    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));
    await userEvent.click(screen.getByRole("button", { name: /select folder/i }));

    expect(api.scan.addRoot).toHaveBeenCalledWith("/picked/path", "{creator}");
    expect(screen.queryByTestId("folder-picker")).toBeNull();
  });
});

describe("Settings – backend error details surfaced (#216)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the backend detail when adding a duplicate root", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.addRoot).mockRejectedValueOnce(new Error("Root already exists"));
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/dup/path");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(await screen.findByText("Root already exists")).toBeInTheDocument();
  });

  it("shows the backend's layout validation message", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.addRoot).mockRejectedValueOnce(
      new Error("Layout must contain the {creator} placeholder")
    );
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/new/path");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(
      await screen.findByText("Layout must contain the {creator} placeholder")
    ).toBeInTheDocument();
  });

  it("falls back to a generic message when the error has no detail", async () => {
    const { api } = await import("../api/client");
    vi.mocked(api.scan.addRoot).mockRejectedValueOnce(new Error(""));
    render(<Settings />);

    await userEvent.type(screen.getByPlaceholderText(/full path/i), "/new/path");
    await userEvent.click(await screen.findByRole("button", { name: /add folder/i }));

    expect(await screen.findByText("Could not add drive")).toBeInTheDocument();
  });
});
