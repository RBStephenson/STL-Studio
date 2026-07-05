// Left column of ModelDetail: image/gallery viewer, thumbnail strip, and the
// lazy 3D STL viewer. Extracted from ModelDetail.tsx (STUDIO-63 P2 PR-2) —
// behavior-preserving. State (active image, gallery index, view mode, selected
// file) is owned by the shell and passed in, because it is shared with the
// lightbox overlay and keyboard-navigation effects.

import { Suspense, lazy } from "react";
import {
  Images, Box, Package, ZoomIn, ImageOff, Bookmark, BookmarkCheck, ImagePlus,
} from "lucide-react";
import { GalleryRotator, GalleryRotatorHandle } from "../../../components/ModelCard";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { useAppSettings } from "../../../context/AppSettingsContext";
import { useConfirm } from "../../../context/ConfirmContext";
import type { ViewMode } from "../utils";

const STLViewer = lazy(() => import("../../../components/STLViewer"));

interface ImageColumnProps {
  model: ModelDetailType;
  hasSTLs: boolean;
  viewMode: ViewMode;
  onSetViewMode: (mode: ViewMode) => void;
  nsfw: boolean;
  showNSFW: boolean;
  rotatorRef: React.RefObject<GalleryRotatorHandle | null>;
  galleryIdx: number;
  onGalleryIndexChange: (idx: number) => void;
  activeImage: string | null;
  onSetActiveImage: (src: string) => void;
  onOpenLightbox: () => void;
  onReload: () => void;
  onClearImage: () => void;
  onOpenImagePicker: () => void;
  stlFilesWithLiveTypes: ModelDetailType["stl_files"];
  selectedStlFileId: number | null;
  onSelectFile: (id: number | null) => void;
}

export default function ImageColumn({
  model,
  hasSTLs,
  viewMode,
  onSetViewMode,
  nsfw,
  showNSFW,
  rotatorRef,
  galleryIdx,
  onGalleryIndexChange,
  activeImage,
  onSetActiveImage,
  onOpenLightbox,
  onReload,
  onClearImage,
  onOpenImagePicker,
  stlFilesWithLiveTypes,
  selectedStlFileId,
  onSelectFile,
}: ImageColumnProps) {
  const { settings } = useAppSettings();
  const confirm = useConfirm();
  const galleryHasThumbnail =
    !!model.thumbnail_path && model.image_paths.some((path) => path === model.thumbnail_path);

  return (
    <div className="flex flex-col gap-3">

      {/* View mode toggle */}
      {hasSTLs && (
        <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1 self-start">
          <button
            onClick={() => onSetViewMode("images")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
              viewMode === "images"
                ? "bg-gray-700 text-gray-100"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            <Images size={14} /> Images
          </button>
          <button
            onClick={() => onSetViewMode("3d")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
              viewMode === "3d"
                ? "bg-indigo-600 text-white"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            <Box size={14} /> 3D View
          </button>
        </div>
      )}

      {/* Image view */}
      {viewMode === "images" && (
        <>
          <div className="aspect-square bg-gray-900 rounded-xl overflow-hidden border border-gray-800 relative group">
            {model.image_paths.length > 0 ? (
              <GalleryRotator
                ref={rotatorRef}
                paths={model.image_paths}
                alt={model.title ?? model.name}
                blur={nsfw && !showNSFW}
                onIndexChange={onGalleryIndexChange}
              />
            ) : activeImage ? (
              <img
                src={activeImage}
                alt={model.title ?? model.name}
                onClick={onOpenLightbox}
                className={`w-full h-full object-contain transition-all cursor-zoom-in ${
                  nsfw && !showNSFW ? "blur-2xl" : ""
                }`}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-700">
                <Package size={64} />
              </div>
            )}

            {/* NSFW detail overlay */}
            {nsfw && !showNSFW && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                <span className="bg-black/70 text-red-400 text-sm font-bold px-3 py-1.5 rounded border border-red-800 tracking-widest">
                  NSFW
                </span>
                <p className="text-xs text-gray-500">Enable NSFW in the navbar to view</p>
              </div>
            )}

            {/* Zoom button */}
            {(model.image_paths.length > 0 || activeImage) && (
              <button
                onClick={onOpenLightbox}
                className="absolute top-3 right-3 p-1.5 rounded-lg bg-black/60 hover:bg-black/80 text-gray-300 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label="View fullscreen"
              >
                <ZoomIn size={14} />
              </button>
            )}

            {/* Hover action bar */}
            <div className="absolute bottom-3 right-3 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
              {model.image_paths.length > 0 ? (
                // Gallery mode: bookmark + delete
                (() => {
                  const currentPath = model.image_paths[galleryIdx] ?? null;
                  const isPrimary = currentPath !== null && currentPath === model.primary_image_path;
                  return (
                    <>
                      <button
                        onClick={async () => {
                          const ok = await confirm({
                            title: "Delete this image?",
                            message: "The image will be removed from this pack. The file remains on disk.",
                            confirmLabel: "Delete image",
                          });
                          if (!ok || currentPath === null) return;
                          const newPaths = model.image_paths.filter((_, i) => i !== galleryIdx);
                          const removed = model.removed_image_paths ?? [];
                          const nextRemoved = removed.includes(currentPath) ? removed : [...removed, currentPath];
                          await api.models.update(model.id, {
                            image_paths: newPaths,
                            removed_image_paths: nextRemoved,
                            ...(model.primary_image_path === currentPath ? { primary_image_path: null } : {}),
                          });
                          onReload();
                        }}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-rose-900/70 text-gray-300 hover:text-white text-xs"
                      >
                        <ImageOff size={13} /> Delete image
                      </button>
                      {isPrimary ? (
                        <button
                          onClick={async () => {
                            await api.models.update(model.id, { primary_image_path: null });
                            onReload();
                          }}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-indigo-700/80 text-indigo-200 text-xs"
                          title="Remove as library card image"
                        >
                          <BookmarkCheck size={13} /> Library image
                        </button>
                      ) : (
                        <button
                          onClick={async () => {
                            await api.models.update(model.id, { primary_image_path: currentPath });
                            onReload();
                          }}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-indigo-700/80 text-gray-300 hover:text-indigo-200 text-xs"
                          title="Use as library card image"
                        >
                          <Bookmark size={13} /> Set as library image
                        </button>
                      )}
                    </>
                  );
                })()
              ) : (
                // Thumbnail mode: clear / change
                <>
                  {activeImage && (
                    <button
                      onClick={onClearImage}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-rose-900/70 text-gray-300 hover:text-white text-xs"
                    >
                      <ImageOff size={13} /> Clear image
                    </button>
                  )}
                  <button
                    onClick={onOpenImagePicker}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-black/80 text-gray-300 hover:text-white text-xs"
                  >
                    <ImagePlus size={13} /> Change image
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Thumbnail strip — explicit thumbnail + gallery sections to avoid index mapping bugs */}
          {(() => {
            const thumbSrc = model.thumbnail_path
              ? api.fileUrl(model.thumbnail_path, model.updated_at)
              : model.thumbnail_url ?? null;
            const showSeparateThumb = !!thumbSrc && !galleryHasThumbnail;
            const totalItems = (showSeparateThumb ? 1 : 0) + model.image_paths.length;
            if (totalItems <= 1) return null;
            return (
              <div className="flex gap-2 flex-wrap">
                {showSeparateThumb && (
                  <button
                    onClick={() => onSetActiveImage(thumbSrc)}
                    className={`w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors ${
                      model.image_paths.length === 0 && activeImage === thumbSrc
                        ? "border-indigo-500"
                        : "border-gray-800 hover:border-gray-600"
                    }`}
                  >
                    <img src={thumbSrc} alt="" className="w-full h-full object-cover" />
                  </button>
                )}
                {model.image_paths.map((path, i) => (
                  <button
                    key={i}
                    onClick={() => rotatorRef.current?.goTo(i)}
                    className={`w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors ${
                      i === galleryIdx ? "border-indigo-500" : "border-gray-800 hover:border-gray-600"
                    }`}
                  >
                    <img src={api.fileUrl(path)} alt="" className="w-full h-full object-cover" />
                  </button>
                ))}
              </div>
            );
          })()}
        </>
      )}

      {/* 3D view — loaded lazily so three.js is not in the initial bundle */}
      {viewMode === "3d" && (
        <Suspense fallback={<div className="flex items-center justify-center h-64 text-gray-400">Loading viewer…</div>}>
          <STLViewer
            files={stlFilesWithLiveTypes}
            getUrl={api.stlUrl}
            modelId={model.id}
            onThumbnailCaptured={onReload}
            categoriesEnabled={settings.part_categories_enabled}
            selectedFileId={selectedStlFileId ?? undefined}
            onSelectFile={onSelectFile}
            hidePicker={settings.horizontal_parts_layout}
          />
        </Suspense>
      )}
    </div>
  );
}
