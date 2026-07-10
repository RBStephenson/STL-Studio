import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { GalleryRotatorHandle } from "../components/ModelCard";
import { useParams, Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Star, Tag, FileBox, Globe, Pencil, FolderDown, Folder, FolderSync, Copy, Check, Printer, Split, X, Paintbrush, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError, ModelDetail as ModelDetailType, AiOrganizePreviewResult, AiOrganizeStrategy } from "../api/client";
import AiOrganizeReviewModal from "../components/AiOrganizeReviewModal";
import AiOrganizeStrategyModal from "../components/AiOrganizeStrategyModal";
import FindOnWeb from "../components/FindOnWeb";
import ImagePicker from "../components/ImagePicker";
import MetadataEditor from "../components/MetadataEditor";
import KitBuilder from "../components/KitBuilder";
import StarRating from "../components/StarRating";
import { useNSFW } from "../context/NSFWContext";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import { queryKeys } from "../hooks/queries/keys";
import { invalidateModelViews } from "../hooks/queries/invalidation";
import { useModel, useModelVariants, useModelNeighbors } from "../hooks/queries/models";
import { useModelGuideId } from "../hooks/queries/guides";
import { useModelTags } from "./model-detail/hooks/useModelTags";
import { usePartEditing } from "./model-detail/hooks/usePartEditing";
import { usePrintStatus } from "./model-detail/hooks/usePrintStatus";
import { useGroupMerge } from "./model-detail/hooks/useGroupMerge";
import CollectionsSection from "./model-detail/CollectionsSection";
import ImageColumn from "./model-detail/sections/ImageColumn";
import StlFilesList from "./model-detail/sections/StlFilesList";
import StlFilesTable from "./model-detail/sections/StlFilesTable";
import VariantSwitcher from "./model-detail/sections/VariantSwitcher";
import StatsRow from "./model-detail/sections/StatsRow";
import TagsPanel from "./model-detail/sections/TagsPanel";
import { errMsg } from "../utils/err";
import {
  toPascalCase,
  parseLibraryOrigin,
  type ViewMode,
  type NavTarget,
} from "./model-detail/utils";

export default function ModelDetail() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const rawFrom = (location.state as { from?: string } | null)?.from;
  const backTo = rawFrom ?? "/";
  const navOrigin = useMemo(() => parseLibraryOrigin(rawFrom), [rawFrom]); // null = not from Library → hide Prev/Next
  const { showNSFW } = useNSFW();
  const { settings } = useAppSettings();
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const numericId = id ? Number(id) : undefined;

  // Server state via TanStack Query (STUDIO-61). The hooks own caching,
  // staleness, and stale-response guarding; the api.models.* slice still does
  // the fetching.
  const modelQuery = useModel(numericId);
  const model = modelQuery.data ?? null;
  const loading = modelQuery.isPending && numericId != null;
  const galleryEnabled = settings.gallery_enabled !== false;
  const effectiveImagePaths = useMemo(
    () => (galleryEnabled ? (model?.image_paths ?? []) : []),
    [galleryEnabled, model?.image_paths],
  );
  // null = no error; "notfound" = 404 (model gone); "network" = transient
  // fetch/5xx failure the user can retry.
  const loadError: "notfound" | "network" | null = modelQuery.error
    ? modelQuery.error instanceof ApiError && modelQuery.error.status === 404
      ? "notfound"
      : "network"
    : null;

  const variantsQuery = useModelVariants(model);
  const variants = variantsQuery.data ?? [];

  // The painting guide for this model, if one exists (#263). null = none/unknown.
  const guideQuery = useModelGuideId(numericId, settings.painting_guides_enabled);
  const guideId = guideQuery.data ?? null;

  const neighborsQuery = useModelNeighbors(numericId, navOrigin);

  // Optimistically patch the cached model in place (e.g. an STL-file field
  // edit), replacing the old setModel updater now that the model lives in the
  // query cache.
  const patchModel = useCallback(
    (updater: (prev: ModelDetailType) => ModelDetailType) => {
      if (numericId == null) return;
      queryClient.setQueryData<ModelDetailType>(
        queryKeys.models.detail(numericId),
        (prev) => (prev ? updater(prev) : prev),
      );
    },
    [numericId, queryClient],
  );

  const [activeImage, setActiveImage] = useState<string | null>(null);
  const [galleryIdx, setGalleryIdx] = useState(0);
  const rotatorRef = useRef<GalleryRotatorHandle>(null);
  const [showFindOnWeb, setShowFindOnWeb] = useState(false);
  const [showImagePicker, setShowImagePicker] = useState(false);
  const [editing, setEditing] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("images");
  const [selectedStlFileId, setSelectedStlFileId] = useState<number | null>(null);
  const [nsfw, setNsfw] = useState(false);
  const [favorite, setFavorite] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const { printStatus, printCount, cyclePrintStatus, clearPrintStatus } = usePrintStatus(model, numericId);
  const {
    tags, removedAutoTags, showHiddenTags, editingTags, tagSuggestions,
    addTag, setUserTags, openTagEditor, doneEditing, toggleHidden,
    suppressAutoTag, restoreAutoTag,
  } = useModelTags(model, numericId);
  const {
    partTypes, setPartTypes, partNames, setPartNames,
    filesCollapsed, setFilesCollapsed, linkingBaseId, setLinkingBaseId,
    savePartType, savePartName, linkSup, unlinkSup,
  } = usePartEditing(model, patchModel, selectedStlFileId);
  const [showKitBuilder, setShowKitBuilder] = useState(false);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [downloadingSelected, setDownloadingSelected] = useState(false);
  const [aiOrganizing, setAiOrganizing] = useState(false);
  const [aiOrganizeResult, setAiOrganizeResult] = useState<AiOrganizePreviewResult | null>(null);
  const [showAiOrganizeStrategy, setShowAiOrganizeStrategy] = useState(false);
  const [copiedPath, setCopiedPath] = useState(false);
  const [openFolderError, setOpenFolderError] = useState<string | null>(null);
  const [splitting, setSplitting] = useState(false);
  // undefined = loading, null = boundary/unavailable, NavTarget = navigable.
  // Derived from the neighbors query: no origin → null (Prev/Next hidden);
  // in-flight → undefined (skeleton); resolved → target or boundary.
  const prevNav = useMemo<NavTarget | null | undefined>(() => {
    if (!navOrigin) return null;
    if (neighborsQuery.isPending) return undefined;
    const pid = neighborsQuery.data?.prev_id ?? null;
    return pid != null ? { id: pid, from: backTo } : null;
  }, [navOrigin, neighborsQuery.isPending, neighborsQuery.data, backTo]);
  const nextNav = useMemo<NavTarget | null | undefined>(() => {
    if (!navOrigin) return null;
    if (neighborsQuery.isPending) return undefined;
    const nid = neighborsQuery.data?.next_id ?? null;
    return nid != null ? { id: nid, from: backTo } : null;
  }, [navOrigin, neighborsQuery.isPending, neighborsQuery.data, backTo]);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  // stl_files merged with live partTypes so STLViewer sees label changes immediately
  const stlFilesWithLiveTypes = useMemo(
    () =>
      (model?.stl_files ?? []).map((f) => ({
        ...f,
        part_type: partTypes[f.id] !== undefined ? (partTypes[f.id] || null) : f.part_type,
      })),
    [model?.stl_files, partTypes],
  );

  // stl_files grouped by PERSISTED part_type so the file list stays stable while
  // the user is typing — DOM elements don't remount mid-edit. Files only move
  // between sections after a successful save (model is updated in-place below).
  const groupedStlFiles = useMemo(() => {
    const labeled = new Map<string, NonNullable<typeof model>["stl_files"]>();
    const unlabeled: NonNullable<typeof model>["stl_files"] = [];
    for (const f of model?.stl_files ?? []) {
      if (f.part_type) {
        const key = toPascalCase(f.part_type);
        if (!labeled.has(key)) labeled.set(key, []);
        labeled.get(key)!.push(f);
      } else {
        unlabeled.push(f);
      }
    }
    const sortedLabeled = [...labeled.entries()].sort(([a], [b]) => a.localeCompare(b));
    return { labeled: sortedLabeled, unlabeled };
  }, [model?.stl_files]);

  useEffect(() => {
    if (!lightboxOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setLightboxOpen(false); return; }
      const hasGallery = effectiveImagePaths.length > 0;
      if (hasGallery) {
        const total = effectiveImagePaths.length;
        if (e.key === "ArrowLeft" && galleryIdx > 0) rotatorRef.current?.goTo(galleryIdx - 1);
        if (e.key === "ArrowRight" && galleryIdx < total - 1) rotatorRef.current?.goTo(galleryIdx + 1);
      } else {
        if (!activeImage) return;
        const allImgs = [
          model?.thumbnail_path ? api.fileUrl(model.thumbnail_path, model.updated_at) : model?.thumbnail_url,
          ...effectiveImagePaths.map((p) => api.fileUrl(p)),
        ].filter(Boolean) as string[];
        const idx = allImgs.indexOf(activeImage);
        if (e.key === "ArrowLeft" && idx > 0) setActiveImage(allImgs[idx - 1]);
        if (e.key === "ArrowRight" && idx < allImgs.length - 1) setActiveImage(allImgs[idx + 1]);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [activeImage, effectiveImagePaths, galleryIdx, lightboxOpen, model]);

  // sync local state from loaded model
  useEffect(() => {
    if (model) {
      setNsfw(model.nsfw);
      setFavorite(model.is_favorite);
      setRating(model.user_rating ?? null);
    }
  }, [model]);

  // Reset the shown image to the thumbnail when the model loads or its thumbnail
  // changes (capture/clear). Keyed on thumbnail identity — not the whole model —
  // so an in-place refresh from an unrelated edit (e.g. saving a part category)
  // doesn't clobber the thumbnail-strip image the user picked.
  useEffect(() => {
    if (!model) return;
    setActiveImage(
      model.thumbnail_path
        ? api.fileUrl(model.thumbnail_path, model.updated_at)
        : model.thumbnail_url ?? null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.thumbnail_path, model?.thumbnail_url, model?.updated_at]);


  // Reset UI-only state when navigating to a different model
  useEffect(() => {
    setEditing(false);
    setShowFindOnWeb(false);
    setShowImagePicker(false);
    setShowKitBuilder(false);
    setOpenFolderError(null);
  }, [id]);

  const downloadAllFiles = async () => {
    if (!model || downloadingAll) return;
    setDownloadingAll(true);
    try {
      const date = new Date().toISOString().slice(0, 10);
      const name = model.title || model.name;
      await api.downloadZip(model.stl_files.map((f) => f.id), `${name} ${date}`);
    } finally {
      setDownloadingAll(false);
    }
  };

  const downloadSelectedFiles = async (fileIds: number[]) => {
    if (!model || downloadingSelected || fileIds.length === 0) return;
    setDownloadingSelected(true);
    try {
      const date = new Date().toISOString().slice(0, 10);
      const name = model.title || model.name;
      await api.downloadZip(fileIds, `${name} ${date}`);
    } finally {
      setDownloadingSelected(false);
    }
  };

  // Button click opens the strategy picker (#878) rather than calling the API
  // directly — the actual call happens in runAiOrganize once a strategy is chosen.
  const runAiOrganize = () => {
    if (!model || aiOrganizing) return;
    setShowAiOrganizeStrategy(true);
  };

  const organizeWithStrategy = async (strategy: AiOrganizeStrategy) => {
    if (!model) return;
    setShowAiOrganizeStrategy(false);
    setAiOrganizing(true);
    try {
      // Always open the modal so the user sees WHY, whether that's a review
      // table (llm_status "ok") or a clear explanation (disabled/skipped/
      // error) — AI Organize never silently substitutes heuristics for a
      // real AI result (#821), so an empty response is still feedback worth
      // surfacing, not a value to swallow into a toast.
      setAiOrganizeResult(await api.models.aiOrganize(model.id, strategy));
    } catch (e) {
      toast(errMsg(e) || "AI organize failed", "error");
    } finally {
      setAiOrganizing(false);
    }
  };

  const copyPath = () => {
    const path = model?.native_folder_path || model?.folder_path || "";
    navigator.clipboard.writeText(path).then(() => {
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 2000);
    });
  };

  const openFolder = async () => {
    if (!model) return;
    setOpenFolderError(null);
    try {
      await api.files.openFolder(model.folder_path);
    } catch {
      setOpenFolderError("Cannot open folder — only available in standalone mode.");
      setTimeout(() => setOpenFolderError(null), 4000);
    }
  };

  const splitPack = async () => {
    if (!model || splitting) return;
    const ok = await confirm({
      title: "Split into separate models?",
      message:
        `Split "${model.title || model.name}" into one model per sub-folder?\n\n` +
        "Use this when a folder is actually a pack of separate models (e.g. a " +
        "multi-character set). This replaces the current model and is remembered " +
        "across rescans.",
      confirmLabel: "Split",
    });
    if (!ok) return;
    setSplitting(true);
    try {
      const res = await api.models.splitPack(model.id);
      toast(`Split into ${res.created} models.`, "success");
      navigate(backTo);   // this model no longer exists
    } catch (e) {
      toast(errMsg(e) || "Couldn't split this model — try again.", "error");
      setSplitting(false);
    }
  };

  // #678 Phase 4: merge into / remove from a durable VariantGroup. Creating a
  // brand-new group from a single ungrouped model is deliberately unsupported
  // here (undesigned UX per the plan) — the picker only accepts an existing
  // group, resolved the same way VariantGroup.tsx's moveToGroup does: look up
  // any current member of that label and take its variant_group_id.
  const clearImage = async () => {
    if (!model) return;
    const ok = await confirm({
      title: "Clear this model's image?",
      message: "The thumbnail will be removed. You can set a new one anytime.",
      confirmLabel: "Clear image",
    });
    if (!ok) return;
    try {
      await api.models.clearThumbnail(model.id);
      toast("Image cleared.", "success");
      load();
    } catch (e) {
      toast(errMsg(e) || "Couldn't clear the image — try again.", "error");
    }
  };

  const deleteOtherFile = async (path: string) => {
    if (!model) return;
    const name = path.split(/[\\/]/).pop() ?? path;
    const ok = await confirm({
      title: "Delete this file?",
      message: `"${name}" will be permanently deleted from disk.`,
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.models.deleteOtherFile(model.id, path);
      toast("File deleted.", "success");
      load();
    } catch (e) {
      toast(errMsg(e) || "Couldn't delete the file — try again.", "error");
    }
  };

  const toggleNSFW = async () => {
    const next = !nsfw;
    setNsfw(next);
    try {
      await api.models.setNSFW(Number(id), next);
      invalidateModelViews(queryClient, { modelId: Number(id), includeVariants: false });
    } catch {
      setNsfw(!next);  // revert on failure
      toast("Couldn't update NSFW flag — try again.", "error");
    }
  };

  const toggleFavorite = async () => {
    const next = !favorite;
    setFavorite(next);
    try {
      await api.models.setFavorite(Number(id), next);
      invalidateModelViews(queryClient, { modelId: Number(id), includeVariants: false });
    } catch {
      setFavorite(!next);  // revert on failure
      toast("Couldn't update favorite — try again.", "error");
    }
  };

  const changeRating = async (next: number | null) => {
    const prev = rating;
    setRating(next);
    try {
      await api.models.setRating(Number(id), next);
      invalidateModelViews(queryClient, { modelId: Number(id), includeVariants: false });
    } catch {
      setRating(prev);  // revert on failure
      toast("Couldn't update rating — try again.", "error");
    }
  };

  // Refetch this model in place (after an edit/capture/split-merge). Also
  // invalidates every variants query so the switcher's sibling thumbnails
  // refresh even though the (creator, character, group) key is unchanged.
  const load = useCallback(() => {
    if (numericId == null) return;
    modelQuery.refetch();
    invalidateModelViews(queryClient, { includeVariants: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericId, queryClient]);

  const {
    settingGroup, groupInput, setGroupInput, savingGroup, groupSuggestions,
    openMergePicker, cancelMerge, mergeIntoGroup, removeFromGroup,
  } = useGroupMerge(model, numericId, load);

  if (loading) return <div className="p-8 text-text-secondary-alt animate-pulse">Loading…</div>;
  if (loadError === "network") {
    return (
      <div className="p-8 flex flex-col items-start gap-3 text-text-secondary">
        <p>Couldn't load this model — check your connection and try again.</p>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-accent-end hover:bg-accent-start text-sm text-white transition-colors"
        >
          <RefreshCw size={14} /> Retry
        </button>
      </div>
    );
  }
  if (!model) return <div className="p-8 text-text-secondary-alt">Model not found.</div>;

  const allImages = [
    model.thumbnail_path ? api.fileUrl(model.thumbnail_path, model.updated_at) : model.thumbnail_url,
    ...effectiveImagePaths.map((p) => api.fileUrl(p)),
  ].filter(Boolean) as string[];

  const hasSTLs = model.stl_files.some((f) =>
    f.filename.toLowerCase().endsWith(".stl")
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <Link to={backTo} className="flex items-center gap-1.5 text-sm text-text-secondary-alt hover:text-text-primary-alt2 w-fit">
          <ArrowLeft size={14} /> Back to Library
        </Link>

        {navOrigin && (
          <div className="flex items-center gap-1">
            {prevNav !== undefined ? (
              prevNav !== null ? (
                <Link
                  to={`/models/${prevNav.id}`}
                  state={{ from: prevNav.from }}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-text-secondary hover:text-text-primary hover:bg-panel-secondary transition-colors"
                >
                  <ChevronLeft size={15} /> Prev
                </Link>
              ) : (
                <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-text-muted-alt cursor-default select-none">
                  <ChevronLeft size={15} /> Prev
                </span>
              )
            ) : (
              <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-text-muted-alt animate-pulse select-none">
                <ChevronLeft size={15} /> Prev
              </span>
            )}

            {nextNav !== undefined ? (
              nextNav !== null ? (
                <Link
                  to={`/models/${nextNav.id}`}
                  state={{ from: nextNav.from }}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-text-secondary hover:text-text-primary hover:bg-panel-secondary transition-colors"
                >
                  Next <ChevronRight size={15} />
                </Link>
              ) : (
                <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-text-muted-alt cursor-default select-none">
                  Next <ChevronRight size={15} />
                </span>
              )
            ) : (
              <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-text-muted-alt animate-pulse select-none">
                Next <ChevronRight size={15} />
              </span>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        {/* Left column — Images / 3D viewer */}
        <ImageColumn
          model={model}
          hasSTLs={hasSTLs}
          viewMode={viewMode}
          onSetViewMode={setViewMode}
          nsfw={nsfw}
          showNSFW={showNSFW}
          rotatorRef={rotatorRef}
          galleryIdx={galleryIdx}
          onGalleryIndexChange={setGalleryIdx}
          activeImage={activeImage}
          onSetActiveImage={setActiveImage}
          onOpenLightbox={() => setLightboxOpen(true)}
          onReload={load}
          onClearImage={clearImage}
          onOpenImagePicker={() => setShowImagePicker(true)}
          stlFilesWithLiveTypes={stlFilesWithLiveTypes}
          selectedStlFileId={selectedStlFileId}
          onSelectFile={setSelectedStlFileId}
        />

        {/* Right column — Info */}
        <div className="flex flex-col gap-4">
          {/* Title above the action row — side-by-side overlapped on long names (#187) */}
          <div className="flex flex-col gap-3">
            <div className="min-w-0">
              {model.character && (
                <p className="text-sm text-indigo-400 mb-1">{model.character}</p>
              )}
              <h1 className="text-2xl font-bold text-text-primary break-words flex items-center gap-2">
                {model.title || model.name}
                {model.unorganized && (
                  <span
                    title="Unorganized — location doesn't match your organize template. Run Reorganize Library to move it."
                    className="inline-flex shrink-0"
                  >
                    <FolderSync size={18} className="text-amber-400" />
                  </span>
                )}
              </h1>
              {model.creator && (
                <p className="text-text-secondary mt-1">by {model.creator.name}</p>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {settings.painting_guides_enabled && guideId != null && (
                <Link
                  to={`/painting/guides/${guideId}`}
                  title="Open the painting guide for this model"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border text-sm transition-colors bg-fuchsia-950/60 border-fuchsia-800 text-fuchsia-300 hover:bg-fuchsia-900/60"
                >
                  <Paintbrush size={14} />
                  Painting guide
                </Link>
              )}
              <button
                onClick={toggleFavorite}
                title={favorite ? "Remove from favorites" : "Add to favorites"}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-sm transition-colors ${
                  favorite
                    ? "bg-yellow-950/60 border-yellow-800 text-yellow-400 hover:bg-yellow-900/60"
                    : "bg-panel-secondary border-border text-text-secondary hover:text-text-primary-alt"
                }`}
              >
                <Star size={14} fill={favorite ? "currentColor" : "none"} />
                Favorite
              </button>
              <div
                className="flex items-center gap-1 px-2 py-1 rounded border bg-panel-secondary border-border"
                title={rating ? `Rated ${rating}/5 — click a star to change, or the same star to clear` : "Rate this model"}
              >
                <StarRating value={rating} onChange={changeRating} size={16} />
              </div>
              <button
                onClick={cyclePrintStatus}
                title={`Print status: ${printStatus} — click to advance`}
                aria-label={`Print status ${printStatus}`}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-sm transition-colors ${
                  printStatus === "queued"
                    ? "bg-sky-950/60 border-sky-800 text-sky-400 hover:bg-sky-900/60"
                    : printStatus === "printing"
                    ? "bg-amber-950/60 border-amber-800 text-amber-400 hover:bg-amber-900/60"
                    : printStatus === "printed"
                    ? "bg-emerald-950/60 border-emerald-800 text-emerald-400 hover:bg-emerald-900/60"
                    : "bg-panel-secondary border-border text-text-secondary hover:text-text-primary-alt"
                }`}
              >
                <Printer size={14} />
                {printStatus === "none" ? "Set status" : printStatus.charAt(0).toUpperCase() + printStatus.slice(1)}
                {printStatus === "printed" && printCount > 0 && (
                  <span className="ml-1 text-xs opacity-70">×{printCount}</span>
                )}
              </button>
              {printStatus !== "none" && (
                <button
                  onClick={clearPrintStatus}
                  title="Clear print status (revert to not set)"
                  aria-label="Clear print status"
                  className="px-2 py-1.5 rounded border border-border bg-panel-secondary text-text-secondary hover:text-text-primary-alt transition-colors"
                >
                  <X size={14} />
                </button>
              )}
              <button
                onClick={toggleNSFW}
                title={nsfw ? "Mark as SFW" : "Mark as NSFW"}
                className={`px-3 py-1.5 rounded border text-sm transition-colors ${
                  nsfw
                    ? "bg-red-950/60 border-red-800 text-red-400 hover:bg-red-900/60"
                    : "bg-panel-secondary border-border text-text-secondary hover:text-text-primary-alt"
                }`}
              >
                {nsfw ? "NSFW ✓" : "NSFW"}
              </button>
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border hover:border-accent-start text-sm text-text-primary-alt2 transition-colors"
              >
                <Pencil size={14} />
                Edit
              </button>
              <button
                onClick={() => setShowFindOnWeb(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border hover:border-accent-start text-sm text-text-primary-alt2 transition-colors"
              >
                <Globe size={14} />
                Find on Web
              </button>
              <button
                onClick={splitPack}
                disabled={splitting}
                title="If this folder is actually a pack of separate models, split it into one model per sub-folder"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border hover:border-accent-start text-sm text-text-primary-alt2 transition-colors disabled:opacity-40"
              >
                <Split size={14} />
                {splitting ? "Splitting…" : "Split pack"}
              </button>
              {model.variant_group_id != null ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={openMergePicker}
                    title="Merge this model into a different group"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-900/50 hover:bg-indigo-800/60 border border-indigo-700 text-sm text-indigo-300 transition-colors"
                  >
                    <Tag size={14} />
                    Group: {model.variant_group?.label ?? model.character ?? "unnamed"}
                  </button>
                  <button
                    onClick={removeFromGroup}
                    title="Remove this model from its group"
                    className="px-2 py-1.5 rounded bg-panel-secondary hover:bg-red-900/40 border border-border hover:border-red-600 text-xs text-text-secondary-alt hover:text-red-400 transition-colors"
                  >
                    ✕
                  </button>
                </div>
              ) : (
                <button
                  onClick={openMergePicker}
                  title="Merge this model into an existing group (persists across rescans)"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border hover:border-accent-start text-sm text-text-primary-alt2 transition-colors"
                >
                  <Tag size={14} />
                  Merge into group
                </button>
              )}
            </div>
          </div>

          {/* ---- Merge-into-group inline form (#678) ---- */}
          {settingGroup && (
            <div className="flex items-center gap-2 px-1 py-2">
              <Tag size={14} className="text-indigo-400 shrink-0" />
              <input
                autoFocus
                type="text"
                list="group-suggestions"
                value={groupInput}
                onChange={(e) => setGroupInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") mergeIntoGroup(); if (e.key === "Escape") cancelMerge(); }}
                placeholder="Existing group name…"
                className="flex-1 px-2 py-1 rounded bg-panel border border-border focus:border-accent-start text-sm text-text-primary-alt outline-none"
              />
              <datalist id="group-suggestions">
                {groupSuggestions.map((s) => <option key={s} value={s} />)}
              </datalist>
              <button
                onClick={mergeIntoGroup}
                disabled={savingGroup || !groupInput.trim()}
                className="px-3 py-1 rounded bg-indigo-700 hover:bg-accent-end text-sm text-white disabled:opacity-40"
              >
                {savingGroup ? "Merging…" : "Merge"}
              </button>
              <button
                onClick={cancelMerge}
                className="px-3 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-sm text-text-secondary"
              >
                Cancel
              </button>
            </div>
          )}

          {/* ---- Edit mode ---- */}
          {editing && (
            <MetadataEditor
              model={model}
              currentTags={tags}
              onSaved={() => { setEditing(false); load(); }}
              onCancel={() => setEditing(false)}
            />
          )}

          {/* ---- Display mode ---- */}
          {!editing && (<>

          {/* Variant switcher — sibling variants of this character. Lets you pick
              the specific variant to print after flagging the model at the group. */}
          <VariantSwitcher
            variants={variants}
            model={model}
            favorite={favorite}
            printStatus={printStatus}
            nsfw={nsfw}
            showNSFW={showNSFW}
            backTo={backTo}
          />

          {/* Stats row */}
          <StatsRow model={model} />

          {model.source_url && (
            <a
              href={model.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300 w-fit"
            >
              <ExternalLink size={14} />
              View on {model.source_site ?? "source"}
            </a>
          )}

          {model.description && (
            <p className="text-sm text-text-secondary leading-relaxed whitespace-pre-line line-clamp-6">
              {model.description}
            </p>
          )}

          {/* User / auto-detected / hidden tags (#411) */}
          <TagsPanel
            tags={tags}
            autoTags={model.auto_tags ?? []}
            removedAutoTags={removedAutoTags}
            editingTags={editingTags}
            tagSuggestions={tagSuggestions}
            showHiddenTags={showHiddenTags}
            onSetUserTags={setUserTags}
            onDoneEditing={doneEditing}
            onOpenEditor={openTagEditor}
            onAdd={addTag}
            onSuppress={suppressAutoTag}
            onRestore={restoreAutoTag}
            onToggleHidden={toggleHidden}
          />

          {/* Collections — always in right column */}
          <CollectionsSection key={model.id} modelId={model.id} initialIds={model.collection_ids} />

          {/* Location — in right column right under collections when horizontal layout */}
          {settings.horizontal_parts_layout && (
            <div>
              <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-1.5 mb-2">
                <Folder size={14} />
                Location
              </h3>
              <div className="bg-panel border border-border-subtle rounded-lg px-3 py-2">
                <p className="text-xs text-text-secondary break-all font-mono leading-relaxed">
                  {model.native_folder_path || model.folder_path}
                </p>
                <div className="flex gap-2 mt-2">
                  <button onClick={copyPath} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary hover:text-text-primary-alt transition-colors">
                    {copiedPath ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                    {copiedPath ? "Copied!" : "Copy path"}
                  </button>
                  <button onClick={openFolder} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary hover:text-text-primary-alt transition-colors">
                    <FolderDown size={11} />
                    Open folder
                  </button>
                </div>
                {openFolderError && <p className="text-xs text-amber-400 mt-1.5">{openFolderError}</p>}
              </div>
            </div>
          )}

          {/* Other Files — in right column when horizontal layout */}
          {settings.horizontal_parts_layout && (model.other_files ?? []).length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-1.5 mb-2">
                <FileBox size={14} />
                Other Files ({(model.other_files ?? []).length})
              </h3>
              <div className="space-y-1">
                {(model.other_files ?? []).map((fp) => {
                  const name = fp.split(/[\\/]/).pop() ?? fp;
                  return (
                    <div key={fp} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-panel border border-border-subtle hover:border-border-divider hover:bg-panel-secondary text-xs text-text-primary-alt2 transition-colors">
                      <a href={api.documentUrl(fp)} download={name} className="flex items-center gap-2 flex-1 min-w-0 hover:text-text-primary">
                        <FileBox size={12} className="shrink-0 text-text-secondary-alt" />
                        <span className="truncate">{name}</span>
                      </a>
                      <button
                        onClick={() => deleteOtherFile(fp)}
                        className="shrink-0 p-1 rounded text-text-muted hover:text-red-400 hover:bg-red-950/40 transition-colors"
                        aria-label={`Delete ${name}`}
                        title={`Delete ${name}`}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* STL Files list — vertical hierarchical layout (non-horizontal) */}
          <StlFilesList
            model={model}
            partTypes={partTypes}
            setPartTypes={setPartTypes}
            savePartType={savePartType}
            selectedStlFileId={selectedStlFileId}
            setSelectedStlFileId={setSelectedStlFileId}
            setViewMode={setViewMode}
            linkingBaseId={linkingBaseId}
            setLinkingBaseId={setLinkingBaseId}
            linkSup={linkSup}
            unlinkSup={unlinkSup}
            filesCollapsed={filesCollapsed}
            setFilesCollapsed={setFilesCollapsed}
            groupedStlFiles={groupedStlFiles}
            aiOrganizing={aiOrganizing}
            runAiOrganize={runAiOrganize}
            downloadingAll={downloadingAll}
            downloadAllFiles={downloadAllFiles}
            onOpenKitBuilder={() => setShowKitBuilder(true)}
          />

          {/* Other Files (PDFs, TXTs, ZIPs, etc.) — right column only when NOT horizontal */}
          {!settings.horizontal_parts_layout && (model.other_files ?? []).length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-1.5 mb-2">
                <FileBox size={14} />
                Other Files ({(model.other_files ?? []).length})
              </h3>
              <div className="space-y-1">
                {(model.other_files ?? []).map((fp) => {
                  const name = fp.split(/[\\/]/).pop() ?? fp;
                  return (
                    <div
                      key={fp}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-panel border border-border-subtle hover:border-border-divider hover:bg-panel-secondary text-xs text-text-primary-alt2 transition-colors"
                    >
                      <a
                        href={api.documentUrl(fp)}
                        download={name}
                        className="flex items-center gap-2 flex-1 min-w-0 hover:text-text-primary"
                      >
                        <FileBox size={12} className="shrink-0 text-text-secondary-alt" />
                        <span className="truncate">{name}</span>
                      </a>
                      <button
                        onClick={() => deleteOtherFile(fp)}
                        className="shrink-0 p-1 rounded text-text-muted hover:text-red-400 hover:bg-red-950/40 transition-colors"
                        aria-label={`Delete ${name}`}
                        title={`Delete ${name}`}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* File location — right column only when NOT horizontal */}
          {!settings.horizontal_parts_layout && <div className="mt-auto">
            <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-1.5 mb-2">
              <Folder size={14} />
              Location
            </h3>
            <div className="bg-panel border border-border-subtle rounded-lg px-3 py-2">
              <p className="text-xs text-text-secondary break-all font-mono leading-relaxed">
                {model.native_folder_path || model.folder_path}
              </p>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={copyPath}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary hover:text-text-primary-alt transition-colors"
                >
                  {copiedPath ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                  {copiedPath ? "Copied!" : "Copy path"}
                </button>
                <button
                  onClick={openFolder}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary hover:text-text-primary-alt transition-colors"
                >
                  <FolderDown size={11} />
                  Open folder
                </button>
              </div>
              {openFolderError && (
                <p className="text-xs text-amber-400 mt-1.5">{openFolderError}</p>
              )}
            </div>
          </div>} {/* end !horizontal_parts_layout for location */}

          </>)} {/* end display mode */}
        </div>
      </div>

      {/* Full-width below-grid area: Collections, Location, STL files table, Other Files */}
      {/* STL Files — horizontal table layout (full-width, below the grid) */}
      <StlFilesTable
        model={model}
        editing={editing}
        partTypes={partTypes}
        setPartTypes={setPartTypes}
        savePartType={savePartType}
        partNames={partNames}
        setPartNames={setPartNames}
        savePartName={savePartName}
        selectedStlFileId={selectedStlFileId}
        setSelectedStlFileId={setSelectedStlFileId}
        setViewMode={setViewMode}
        linkingBaseId={linkingBaseId}
        setLinkingBaseId={setLinkingBaseId}
        linkSup={linkSup}
        unlinkSup={unlinkSup}
        groupedStlFiles={groupedStlFiles}
        aiOrganizing={aiOrganizing}
        runAiOrganize={runAiOrganize}
        downloadingAll={downloadingAll}
        downloadAllFiles={downloadAllFiles}
        downloadingSelected={downloadingSelected}
        downloadSelectedFiles={downloadSelectedFiles}
        onOpenKitBuilder={() => setShowKitBuilder(true)}
      />

      {showImagePicker && (
        <ImagePicker
          modelId={model.id}
          currentPath={model.thumbnail_path}
          currentUrl={model.thumbnail_url ?? null}
          cacheKey={model.character ? `${model.creator_id}:${model.character}` : undefined}
          onApplied={() => { setShowImagePicker(false); load(); }}
          onClose={() => setShowImagePicker(false)}
        />
      )}

      {showFindOnWeb && (
        <FindOnWeb
          modelId={model.id}
          modelName={model.title || model.name}
          onApplied={() => { setShowFindOnWeb(false); load(); }}
          onClose={() => setShowFindOnWeb(false)}
        />
      )}

      {showKitBuilder && (
        <KitBuilder
          modelName={model.title || model.name}
          files={model.stl_files.map((f) => ({ ...f, part_type: partTypes[f.id] || f.part_type }))}
          onClose={() => setShowKitBuilder(false)}
        />
      )}

      {showAiOrganizeStrategy && (
        <AiOrganizeStrategyModal
          onChoose={organizeWithStrategy}
          onClose={() => setShowAiOrganizeStrategy(false)}
        />
      )}

      {aiOrganizeResult && (
        <AiOrganizeReviewModal
          modelId={model.id}
          result={aiOrganizeResult}
          stlFiles={model.stl_files}
          onApplied={() => { setAiOrganizeResult(null); load(); }}
          onClose={() => setAiOrganizeResult(null)}
        />
      )}

      {lightboxOpen && (() => {
        const hasGallery = effectiveImagePaths.length > 0;
        const lbImages = hasGallery
          ? effectiveImagePaths.map((p) => api.fileUrl(p))
          : allImages;
        const lbIdx = hasGallery ? galleryIdx : allImages.indexOf(activeImage ?? "");
        const lbSrc = lbImages[lbIdx] ?? null;
        if (!lbSrc) return null;
        return (
          <div
            className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
            onClick={() => setLightboxOpen(false)}
          >
            <button
              onClick={() => setLightboxOpen(false)}
              className="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
              aria-label="Close"
            >
              <X size={20} />
            </button>

            {lbIdx > 0 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (hasGallery) rotatorRef.current?.goTo(lbIdx - 1);
                  else setActiveImage(lbImages[lbIdx - 1]);
                }}
                className="absolute left-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
                aria-label="Previous image"
              >
                <ChevronLeft size={28} />
              </button>
            )}

            <img
              src={lbSrc}
              alt={model.title ?? model.name}
              onClick={(e) => e.stopPropagation()}
              className={`max-w-[90vw] max-h-[90vh] object-contain rounded-lg ${
                nsfw && !showNSFW ? "blur-2xl" : ""
              }`}
            />

            {lbIdx < lbImages.length - 1 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (hasGallery) rotatorRef.current?.goTo(lbIdx + 1);
                  else setActiveImage(lbImages[lbIdx + 1]);
                }}
                className="absolute right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
                aria-label="Next image"
              >
                <ChevronRight size={28} />
              </button>
            )}

            {lbImages.length > 1 && (
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-white/60 bg-black/40 px-3 py-1 rounded-full">
                {lbIdx + 1} / {lbImages.length}
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
