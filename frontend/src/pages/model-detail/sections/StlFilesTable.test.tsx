import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

let settings: Record<string, boolean>;
beforeEach(() => {
  settings = {
    horizontal_parts_layout: true,
    part_categories_enabled: false,
    ai_organize_enabled: false,
  };
});

vi.mock("../../../api/client", () => ({
  api: { stlUrl: (p: string) => p },
}));
vi.mock("../../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings }),
}));
vi.mock("../../../components/PartTypeCombo", () => ({
  PartTypeCombo: ({ value }: { value: string }) => <input data-testid="part-combo" defaultValue={value} />,
}));

import StlFilesTable from "./StlFilesTable";
import { ModelDetail as ModelDetailType } from "../../../api/client";

type StlFiles = ModelDetailType["stl_files"];

const file = (id: number, filename: string, over: Partial<StlFiles[number]> = {}) =>
  ({ id, filename, path: `/${filename}`, size_bytes: 1_048_576, sup_of_id: null, part_type: null, part_name: null, ...over } as StlFiles[number]);

const model = {
  id: 1,
  stl_files: [file(1, "arm.stl"), file(2, "body.stl")],
} as unknown as ModelDetailType;

const renderTable = (props: Partial<React.ComponentProps<typeof StlFilesTable>> = {}) => {
  const defaults: React.ComponentProps<typeof StlFilesTable> = {
    model,
    editing: false,
    partTypes: {},
    setPartTypes: vi.fn(),
    savePartType: vi.fn(),
    partNames: {},
    setPartNames: vi.fn(),
    savePartName: vi.fn(),
    selectedStlFileId: null,
    setSelectedStlFileId: vi.fn(),
    setViewMode: vi.fn(),
    linkingBaseId: null,
    setLinkingBaseId: vi.fn(),
    linkSup: vi.fn(),
    unlinkSup: vi.fn(),
    groupedStlFiles: { labeled: [], unlabeled: model.stl_files },
    aiOrganizing: false,
    runAiOrganize: vi.fn(),
    downloadingAll: false,
    downloadAllFiles: vi.fn(),
    downloadingSelected: false,
    downloadSelectedFiles: vi.fn(),
    onOpenKitBuilder: vi.fn(),
    ...props,
  };
  return render(<StlFilesTable {...defaults} />);
};

describe("StlFilesTable", () => {
  it("renders nothing when horizontal layout is off", () => {
    settings.horizontal_parts_layout = false;
    const { container } = renderTable();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while editing", () => {
    const { container } = renderTable({ editing: true });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a row per file with a part-name input", () => {
    renderTable();
    expect(screen.getByText("Files (2)")).toBeInTheDocument();
    expect(screen.getByText("arm.stl")).toBeInTheDocument();
    expect(screen.getByText("body.stl")).toBeInTheDocument();
    // Name column input uses autoPartName as placeholder
    expect(screen.getByPlaceholderText("arm")).toBeInTheDocument();
  });

  it("selects a file and switches to 3D on row click", () => {
    const setSelectedStlFileId = vi.fn();
    const setViewMode = vi.fn();
    renderTable({ setSelectedStlFileId, setViewMode });
    fireEvent.click(screen.getByText("arm.stl"));
    expect(setSelectedStlFileId).toHaveBeenCalledWith(1);
    expect(setViewMode).toHaveBeenCalledWith("3d");
  });

  it("saves a renamed part on blur when the value changed", () => {
    const savePartName = vi.fn();
    renderTable({ savePartName });
    const input = screen.getByPlaceholderText("arm");
    fireEvent.change(input, { target: { value: "Left Arm" } });
    fireEvent.blur(input, { target: { value: "Left Arm" } });
    expect(savePartName).toHaveBeenCalledWith(1, "Left Arm");
  });

  it("shows the Category column only when part categories are enabled", () => {
    settings.part_categories_enabled = true;
    renderTable({
      groupedStlFiles: { labeled: [["Arms", [model.stl_files[0]]]], unlabeled: [model.stl_files[1]] },
    });
    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getAllByTestId("part-combo").length).toBeGreaterThan(0);
  });

  it("wires Download all and Kit Builder actions", () => {
    const downloadAllFiles = vi.fn();
    const onOpenKitBuilder = vi.fn();
    renderTable({ downloadAllFiles, onOpenKitBuilder });
    fireEvent.click(screen.getByRole("button", { name: /Download all/ }));
    expect(downloadAllFiles).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Kit Builder/ }));
    expect(onOpenKitBuilder).toHaveBeenCalled();
  });

  it("hides Download selected until a row is checked, then wires it with the checked ids", () => {
    const downloadSelectedFiles = vi.fn();
    renderTable({ downloadSelectedFiles });
    expect(screen.queryByRole("button", { name: /Download selected/ })).not.toBeInTheDocument();

    // Row checkboxes: index 0 is "select all" in the header.
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);

    const button = screen.getByRole("button", { name: /Download selected \(1\)/ });
    fireEvent.click(button);
    expect(downloadSelectedFiles).toHaveBeenCalledWith([1]);
  });

  it("selects every file via the header checkbox", () => {
    const downloadSelectedFiles = vi.fn();
    renderTable({ downloadSelectedFiles });
    const [selectAll] = screen.getAllByRole("checkbox");
    fireEvent.click(selectAll);
    fireEvent.click(screen.getByRole("button", { name: /Download selected \(2\)/ }));
    expect(downloadSelectedFiles).toHaveBeenCalledWith([1, 2]);
  });

  it("shows a drag grip per row when part categories are enabled", () => {
    settings.part_categories_enabled = true;
    renderTable({
      groupedStlFiles: { labeled: [["Arms", [model.stl_files[0]]]], unlabeled: [model.stl_files[1]] },
    });
    expect(screen.getAllByTitle("Drag onto a category to assign it").length).toBe(2);
  });

  it("hides the drag grip when part categories are disabled", () => {
    renderTable();
    expect(screen.queryByTitle("Drag onto a category to assign it")).not.toBeInTheDocument();
  });

  it("hides the recategorize dropdown until a row is checked, and offers standard plus this model's used categories", () => {
    settings.part_categories_enabled = true;
    renderTable({
      groupedStlFiles: { labeled: [["Quetzlgor", [model.stl_files[0]]]], unlabeled: [model.stl_files[1]] },
    });
    expect(screen.queryByText("Recategorize to…")).not.toBeInTheDocument();

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);

    expect(screen.getByText("Recategorize to…")).toBeInTheDocument();
    // Standard suggestion...
    expect(screen.getByRole("option", { name: "Head" })).toBeInTheDocument();
    // ...and this model's own custom category, both offered together.
    expect(screen.getByRole("option", { name: "Quetzlgor" })).toBeInTheDocument();
  });

  it("link-sup picker shows the part name, not the filename, and lets you type to filter", () => {
    const namedModel = {
      id: 1,
      stl_files: [
        file(1, "arm.stl"),
        file(2, "body.stl", { part_name: "Body Armor" }),
        file(3, "head.stl", { part_name: "Head" }),
      ],
    } as unknown as ModelDetailType;
    renderTable({
      model: namedModel,
      groupedStlFiles: { labeled: [], unlabeled: namedModel.stl_files },
      linkingBaseId: 1,
    });

    const input = screen.getByPlaceholderText("Link sup…");
    fireEvent.focus(input);

    expect(screen.getByText("Body Armor")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "body" } });
    expect(screen.getByText("Body Armor")).toBeInTheDocument();
    expect(screen.queryByText("Head")).not.toBeInTheDocument();
  });

  it("hides the recategorize dropdown entirely when part categories are disabled", () => {
    renderTable();
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    expect(screen.queryByText("Recategorize to…")).not.toBeInTheDocument();
  });

  it("recategorizes every checked file and clears the selection on pick", async () => {
    const savePartType = vi.fn().mockResolvedValue(undefined);
    const downloadSelectedFiles = vi.fn();
    settings.part_categories_enabled = true;
    renderTable({ savePartType, downloadSelectedFiles, groupedStlFiles: { labeled: [], unlabeled: model.stl_files } });

    const [selectAll] = screen.getAllByRole("checkbox");
    fireEvent.click(selectAll);
    expect(screen.getByRole("button", { name: /Download selected \(2\)/ })).toBeInTheDocument();

    const dropdown = screen.getByText("Recategorize to…").closest("select")!;
    fireEvent.change(dropdown, { target: { value: "Head" } });

    expect(savePartType).toHaveBeenCalledWith(1, "Head");
    expect(savePartType).toHaveBeenCalledWith(2, "Head");
    // Selection cleared afterward — the download-selected button disappears.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Download selected/ })).not.toBeInTheDocument()
    );
  });
});
