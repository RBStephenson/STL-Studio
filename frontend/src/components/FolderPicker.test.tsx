import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FolderPicker from "./FolderPicker";

const browseMock = vi.fn();
vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return { ...orig, api: { scan: { browse: (...args: unknown[]) => browseMock(...args) } } };
});

describe("FolderPicker (STUDIO-389 file selection)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("navigates into a folder entry instead of selecting it", async () => {
    browseMock
      .mockResolvedValueOnce({
        path: "/library", parent: null, is_drive_list: false,
        entries: [{ name: "Abe3D", path: "/library/Abe3D", is_dir: true }],
      })
      .mockResolvedValueOnce({
        path: "/library/Abe3D", parent: "/library", is_drive_list: false,
        entries: [],
      });

    const onSelect = vi.fn();
    render(<FolderPicker onSelect={onSelect} onClose={() => {}} fileExtensions="zip" />);

    await userEvent.click(await screen.findByText("Abe3D"));

    expect(onSelect).not.toHaveBeenCalled();
    expect(browseMock).toHaveBeenLastCalledWith("/library/Abe3D", undefined, "zip");
  });

  it("selects a file entry immediately on click, without navigating", async () => {
    browseMock.mockResolvedValueOnce({
      path: "/library/Abe3D", parent: "/library", is_drive_list: false,
      entries: [{ name: "zarana.zip", path: "/library/Abe3D/zarana.zip", is_dir: false }],
    });

    const onSelect = vi.fn();
    render(<FolderPicker onSelect={onSelect} onClose={() => {}} fileExtensions="zip" initialPath="/library/Abe3D" />);

    await userEvent.click(await screen.findByText("zarana.zip"));

    expect(onSelect).toHaveBeenCalledWith("/library/Abe3D/zarana.zip");
    // Only the initial browse call — selecting a file must not trigger a second browse.
    expect(browseMock).toHaveBeenCalledTimes(1);
  });

  it("passes no file_extensions param when the prop is omitted (plain folder picker)", async () => {
    browseMock.mockResolvedValueOnce({
      path: "/library", parent: null, is_drive_list: false, entries: [],
    });

    render(<FolderPicker onSelect={() => {}} onClose={() => {}} />);

    await screen.findByText("Choose a folder");
    expect(browseMock).toHaveBeenCalledWith(undefined, undefined, undefined);
  });
});
