import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { createRef } from "react";
import type { GalleryRotatorHandle } from "../../../components/ModelCard";

const mockState = vi.hoisted(() => ({
  settings: {
    part_categories_enabled: true,
    horizontal_parts_layout: false,
    gallery_enabled: true,
    gallery_auto_rotate: true,
    gallery_rotation_seconds: 10,
  },
  galleryProps: null as Record<string, unknown> | null,
}));

const { MockApiError } = vi.hoisted(() => ({
  MockApiError: class extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock("../../../api/client", () => ({
  ApiError: MockApiError,
  api: {
    fileUrl: (p: string) => p,
    stlUrl: (p: string) => p,
    models: {
      update: vi.fn(async () => ({})),
      setThumbnail: vi.fn(async () => ({})),
      refreshGallery: vi.fn(async () => ({})),
      uploadGalleryImages: vi.fn(async () => ({})),
    },
  },
}));
vi.mock("../../../context/AppSettingsContext", () => ({
  useAppSettings: () => ({ settings: mockState.settings }),
}));
vi.mock("../../../context/ConfirmContext", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("../../../components/ModelCard", () => ({
  GalleryRotator: (props: Record<string, unknown>) => {
    mockState.galleryProps = props;
    return <div data-testid="gallery-rotator" />;
  },
}));
vi.mock("../../../components/STLViewer", () => ({ default: () => <div data-testid="stl-viewer" /> }));

import ImageColumn from "./ImageColumn";
import { ModelDetail as ModelDetailType } from "../../../api/client";

const baseModel = {
  id: 1,
  name: "Hero",
  title: "Hero",
  image_paths: [],
  removed_image_paths: [],
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
  beforeEach(() => {
    mockState.settings.gallery_enabled = true;
    mockState.settings.gallery_auto_rotate = true;
    mockState.settings.gallery_rotation_seconds = 10;
    mockState.galleryProps = null;
  });

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

  it("passes gallery rotation preferences to the rotator", () => {
    mockState.settings.gallery_auto_rotate = false;
    mockState.settings.gallery_rotation_seconds = 20;
    renderCol({ model: { ...baseModel, image_paths: ["a.png", "b.png"] } as ModelDetailType });
    expect(mockState.galleryProps).toMatchObject({ autoRotate: false, rotationMs: 20000 });
  });

  it("falls back to a static image when the gallery is disabled", () => {
    mockState.settings.gallery_enabled = false;
    renderCol({
      model: { ...baseModel, image_paths: ["a.png", "b.png"] } as ModelDetailType,
      activeImage: "thumb.png",
    });
    expect(screen.queryByTestId("gallery-rotator")).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("src", "thumb.png");
  });

  it("shows the placeholder icon instead of a broken image when activeImage fails to load", () => {
    renderCol({ activeImage: "gone.png" });

    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "gone.png");
    fireEvent.error(img);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("does not render a duplicate thumbnail strip item when the thumbnail is in the gallery", () => {
    const { container } = renderCol({
      model: { ...baseModel, thumbnail_path: "a.png", image_paths: ["a.png", "b.png"] } as ModelDetailType,
    });
    expect(container.querySelectorAll('img[src="a.png"]')).toHaveLength(1);
  });

  it("persists deleted gallery images as removed image paths", async () => {
    const { api } = await import("../../../api/client");
    renderCol({
      model: {
        ...baseModel,
        image_paths: ["a.png", "b.png"],
        removed_image_paths: ["old.png"],
        primary_image_path: "a.png",
      } as ModelDetailType,
    });

    fireEvent.click(screen.getByRole("button", { name: /Delete image/ }));

    await waitFor(() => {
      expect(api.models.update).toHaveBeenCalledWith(1, {
        image_paths: ["b.png"],
        removed_image_paths: ["old.png", "a.png"],
        primary_image_path: null,
      });
    });
  });

  it("sets the current local gallery image as the thumbnail", async () => {
    const { api } = await import("../../../api/client");
    const onReload = vi.fn();
    renderCol({
      model: { ...baseModel, thumbnail_path: "old.png", image_paths: ["a.png", "b.png"] } as ModelDetailType,
      onReload,
    });

    fireEvent.click(screen.getByRole("button", { name: /Set thumbnail/ }));

    await waitFor(() => {
      expect(api.models.setThumbnail).toHaveBeenCalledWith(1, {
        thumbnail_path: "a.png",
        thumbnail_url: null,
      });
      expect(onReload).toHaveBeenCalled();
    });
  });

  it("does not offer set thumbnail for remote gallery images", () => {
    renderCol({
      model: {
        ...baseModel,
        thumbnail_path: "old.png",
        image_paths: ["https://cdn.example.test/a.png"],
      } as ModelDetailType,
    });

    expect(screen.queryByRole("button", { name: /Set thumbnail/ })).not.toBeInTheDocument();
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

  it("uploads the chosen files and reloads on success", async () => {
    const { api } = await import("../../../api/client");
    const onReload = vi.fn();
    const { container } = renderCol({ onReload });

    const file = new File(["bytes"], "gallery_00.jpg", { type: "image/jpeg" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(api.models.uploadGalleryImages).toHaveBeenCalledWith(1, [file]);
      expect(onReload).toHaveBeenCalled();
    });
  });

  it("shows an error message when the upload fails", async () => {
    const { api } = await import("../../../api/client");
    vi.mocked(api.models.uploadGalleryImages).mockRejectedValueOnce(
      new MockApiError(413, "Image too large (max 15 MB)")
    );
    const { container } = renderCol();

    const file = new File(["bytes"], "big.jpg", { type: "image/jpeg" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("Image too large (max 15 MB)")).toBeInTheDocument();
  });

  it("re-syncs the gallery from disk on Refresh click", async () => {
    const { api } = await import("../../../api/client");
    const onReload = vi.fn();
    renderCol({ onReload });

    fireEvent.click(screen.getByTitle(/re-sync with images placed directly/i));

    await waitFor(() => {
      expect(api.models.refreshGallery).toHaveBeenCalledWith(1);
      expect(onReload).toHaveBeenCalled();
    });
  });

  it("hides a gallery thumbnail whose image fails to load, instead of a broken icon", () => {
    const { container } = renderCol({
      model: { ...baseModel, image_paths: ["a.png", "broken.png"] } as ModelDetailType,
    });

    const brokenImg = container.querySelector('img[src="broken.png"]') as HTMLImageElement;
    expect(brokenImg).toBeInTheDocument();
    fireEvent.error(brokenImg);

    expect(container.querySelector('img[src="broken.png"]')).not.toBeInTheDocument();
    // The sibling thumbnail is unaffected.
    expect(container.querySelector('img[src="a.png"]')).toBeInTheDocument();
  });
});
