import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import KitBuilder from "./KitBuilder";
import { STLFile } from "../api/client";

vi.mock("./STLViewer", () => ({ default: () => <div data-testid="stl-viewer" /> }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: { stlUrl: (p: string) => p, downloadZip: vi.fn() },
  };
});

const file = (id: number, filename: string, over: Partial<STLFile> = {}): STLFile => ({
  id, filename, path: `/${filename}`, size_bytes: 1_000_000,
  part_type: "Weapon", part_name: null, sup_of_id: null, ...over,
});

const renderKitBuilder = (files: STLFile[], onClose = vi.fn()) =>
  render(
    <MemoryRouter>
      <KitBuilder modelName="Test Model" files={files} onClose={onClose} />
    </MemoryRouter>
  );

describe("KitBuilder", () => {
  it("renders a plain pill for a part with no linked variants", () => {
    renderKitBuilder([file(1, "sword.stl")]);
    expect(screen.getByRole("button", { name: /sword/i })).toBeInTheDocument();
  });

  it("clusters a base and its linked sup into one box with a variant row", () => {
    const files = [
      file(1, "sword.stl"),
      file(2, "sword-supported.stl", { sup_of_id: 1 }),
    ];
    renderKitBuilder(files);
    expect(screen.getByRole("button", { name: /^sword$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /supported/i })).toBeInTheDocument();
    // The sup itself must not also render as its own separate top-level pill.
    expect(screen.queryByRole("button", { name: /sword supported/i })).not.toBeInTheDocument();
  });

  it("labels a hollowed variant distinctly from a supported one", () => {
    const files = [
      file(1, "gargoyle.stl"),
      file(2, "gargoyle-hollowed.stl", { sup_of_id: 1 }),
    ];
    renderKitBuilder(files);
    expect(screen.getByRole("button", { name: /hollowed/i })).toBeInTheDocument();
  });

  it("labels a linked variant with no recognized keyword as Other", () => {
    const files = [
      file(1, "widget.stl"),
      file(2, "widget-v2.stl", { sup_of_id: 1 }),
    ];
    renderKitBuilder(files);
    expect(screen.getByRole("button", { name: /other/i })).toBeInTheDocument();
  });

  it("an orphaned sup (base not present in the file list) renders as its own standalone pill", () => {
    const files = [file(2, "sword-supported.stl", { sup_of_id: 999 })];
    renderKitBuilder(files);
    expect(screen.getByRole("button", { name: /sword supported/i })).toBeInTheDocument();
  });

  it("selecting a base and its variant are independent, not mutually exclusive", async () => {
    const files = [
      file(1, "sword.stl"),
      file(2, "sword-supported.stl", { sup_of_id: 1 }),
    ];
    renderKitBuilder(files);

    fireEvent.click(screen.getByRole("button", { name: /^sword$/i }));
    fireEvent.click(screen.getByRole("button", { name: /supported/i }));

    expect(screen.getByText(/2 selected/)).toBeInTheDocument();
    expect(await screen.findByTestId("stl-viewer")).toBeInTheDocument();
  });

  it("clicking a selected item again deselects just that item", () => {
    const files = [
      file(1, "sword.stl"),
      file(2, "sword-supported.stl", { sup_of_id: 1 }),
    ];
    renderKitBuilder(files);

    const base = screen.getByRole("button", { name: /^sword$/i });
    const variant = screen.getByRole("button", { name: /supported/i });
    fireEvent.click(base);
    fireEvent.click(variant);
    expect(screen.getByText(/2 selected/)).toBeInTheDocument();

    fireEvent.click(base);
    expect(screen.getByText(/1 selected/)).toBeInTheDocument();
  });

  it("Clear resets every selection, including inside variant clusters", () => {
    const files = [
      file(1, "sword.stl"),
      file(2, "sword-supported.stl", { sup_of_id: 1 }),
    ];
    renderKitBuilder(files);
    fireEvent.click(screen.getByRole("button", { name: /^sword$/i }));
    fireEvent.click(screen.getByRole("button", { name: /supported/i }));

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText(/Click parts above to build your selection/)).toBeInTheDocument();
  });

  it("shows the empty state when the model has no STL files", () => {
    renderKitBuilder([]);
    expect(screen.getByText("No STL files found for this model.")).toBeInTheDocument();
  });
});
