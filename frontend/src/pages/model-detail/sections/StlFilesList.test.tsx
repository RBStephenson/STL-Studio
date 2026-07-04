import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

let settings: Record<string, boolean>;
beforeEach(() => {
  settings = {
    horizontal_parts_layout: false,
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

import StlFilesList from "./StlFilesList";
import { ModelDetail as ModelDetailType } from "../../../api/client";

type StlFiles = ModelDetailType["stl_files"];

const file = (id: number, filename: string, over: Partial<StlFiles[number]> = {}) =>
  ({ id, filename, path: `/${filename}`, size_bytes: 1_048_576, sup_of_id: null, part_type: null, part_name: null, ...over } as StlFiles[number]);

const model = {
  id: 1,
  stl_files: [file(1, "arm.stl"), file(2, "body.stl")],
} as unknown as ModelDetailType;

const renderList = (props: Partial<React.ComponentProps<typeof StlFilesList>> = {}) => {
  const defaults: React.ComponentProps<typeof StlFilesList> = {
    model,
    partTypes: {},
    setPartTypes: vi.fn(),
    savePartType: vi.fn(),
    selectedStlFileId: null,
    setSelectedStlFileId: vi.fn(),
    setViewMode: vi.fn(),
    linkingBaseId: null,
    setLinkingBaseId: vi.fn(),
    linkSup: vi.fn(),
    unlinkSup: vi.fn(),
    filesCollapsed: new Set(),
    setFilesCollapsed: vi.fn(),
    groupedStlFiles: { labeled: [], unlabeled: model.stl_files },
    aiOrganizing: false,
    runAiOrganize: vi.fn(),
    downloadingAll: false,
    downloadAllFiles: vi.fn(),
    onOpenKitBuilder: vi.fn(),
    ...props,
  };
  return render(<StlFilesList {...defaults} />);
};

describe("StlFilesList", () => {
  it("renders nothing in horizontal layout", () => {
    settings.horizontal_parts_layout = true;
    const { container } = renderList();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the file count and both filenames (alpha layout)", () => {
    renderList();
    expect(screen.getByText("Files (2)")).toBeInTheDocument();
    expect(screen.getByText("arm.stl")).toBeInTheDocument();
    expect(screen.getByText("body.stl")).toBeInTheDocument();
  });

  it("selects a file and switches to 3D on row click", () => {
    const setSelectedStlFileId = vi.fn();
    const setViewMode = vi.fn();
    renderList({ setSelectedStlFileId, setViewMode });
    fireEvent.click(screen.getByText("arm.stl"));
    expect(setSelectedStlFileId).toHaveBeenCalledWith(1);
    expect(setViewMode).toHaveBeenCalledWith("3d");
  });

  it("renders category combos only when part categories are enabled", () => {
    settings.part_categories_enabled = true;
    renderList({
      groupedStlFiles: { labeled: [["Arms", [model.stl_files[0]]]], unlabeled: [model.stl_files[1]] },
    });
    expect(screen.getAllByTestId("part-combo").length).toBeGreaterThan(0);
  });

  it("wires the Download all and Kit Builder actions", () => {
    const downloadAllFiles = vi.fn();
    const onOpenKitBuilder = vi.fn();
    renderList({ downloadAllFiles, onOpenKitBuilder });
    fireEvent.click(screen.getByRole("button", { name: /Download all/ }));
    expect(downloadAllFiles).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Kit Builder/ }));
    expect(onOpenKitBuilder).toHaveBeenCalled();
  });

  it("toggles the sup-linking picker for a base file", () => {
    const setLinkingBaseId = vi.fn();
    renderList({ setLinkingBaseId });
    fireEvent.click(screen.getAllByTitle("Link a supported version")[0]);
    expect(setLinkingBaseId).toHaveBeenCalledWith(1);
  });
});
