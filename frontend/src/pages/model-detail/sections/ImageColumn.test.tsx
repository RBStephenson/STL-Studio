import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { createRef } from "react";
import type { GalleryRotatorHandle } from "../../../components/ModelCard";

vi.mock("../../../api/client", () => ({
  api: {
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
    models: { update: vi.fn(async () => ({})) },
  },
}));
vi.mock("../../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: { part_categories_enabled: true, horizontal_parts_layout: false } }),
}));
vi.mock("../../../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("../../../components/ModelCard", () => ({
  GalleryRotator: () => <div data-testid="gallery-rotator" />,
}));
vi.mock("../../../components/STLViewer", () => ({ default: () => <div data-testid="stl-viewer" /> }));

import ImageColumn from "./ImageColumn";
import { ModelDetail as ModelDetailType } from "../../../api/client";

const baseModel = {
  id: 1,
  name: "Hero",
  title: "Hero",
  image_paths: [],
  thumbnail_path: null,
  thumbnail_url: null,
  primary_image_path: null,
  updated_at: null,
  stl_files: [],
} as unknown as ModelDetailType;

const renderCol = (props: Partial<React.ComponentProps<typeof ImageColumn>> = {}) => {
  const defaults: React.ComponentProps<typeof ImageColumn> = {
    model: baseModel,
    hasSTLs: false,
    viewMode: "images",
    onSetViewMode: vi.fn(),
    nsfw: false,
    showNSFW: false,
    rotatorRef: createRef<GalleryRotatorHandle>(),
    galleryIdx: 0,
    onGalleryIndexChange: vi.fn(),
    activeImage: null,
    onSetActiveImage: vi.fn(),
    onOpenLightbox: vi.fn(),
    onReload: vi.fn(),
    onClearImage: vi.fn(),
    onOpenImagePicker: vi.fn(),
    stlFilesWithLiveTypes: [],
    selectedStlFileId: null,
    onSelectFile: vi.fn(),
    ...props,
  };
  return render(
    <MemoryRouter>
      <ImageColumn {...defaults} />
    </MemoryRouter>
  );
};

describe("ImageColumn", () => {
  it("hides the view-mode toggle when there are no STL files", () => {
    renderCol({ hasSTLs: false });
    expect(screen.queryByRole("button", { name: /3D View/ })).not.toBeInTheDocument();
  });

  it("shows the toggle when STLs exist and switches mode on click", () => {
    const onSetViewMode = vi.fn();
    renderCol({ hasSTLs: true, onSetViewMode });
    fireEvent.click(screen.getByRole("button", { name: /3D View/ }));
    expect(onSetViewMode).toHaveBeenCalledWith("3d");
  });

  it("renders the gallery rotator when the model has image paths", () => {
    renderCol({ model: { ...baseModel, image_paths: ["a.png", "b.png"] } as ModelDetailType });
    expect(screen.getByTestId("gallery-rotator")).toBeInTheDocument();
  });

  it("shows the NSFW overlay when flagged and NSFW is hidden", () => {
    renderCol({ nsfw: true, showNSFW: false });
    expect(screen.getByText("NSFW")).toBeInTheDocument();
  });

  it("fires onOpenImagePicker from the thumbnail-mode Change image button", () => {
    const onOpenImagePicker = vi.fn();
    renderCol({ onOpenImagePicker });
    fireEvent.click(screen.getByRole("button", { name: /Change image/ }));
    expect(onOpenImagePicker).toHaveBeenCalled();
  });

  it("renders the lazy STL viewer in 3d mode", async () => {
    renderCol({ hasSTLs: true, viewMode: "3d" });
    expect(await screen.findByTestId("stl-viewer")).toBeInTheDocument();
  });
});
