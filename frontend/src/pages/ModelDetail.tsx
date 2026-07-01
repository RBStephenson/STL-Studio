import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense, Fragment } from "react";
import { GalleryRotator, GalleryRotatorHandle } from "../components/ModelCard";
import { useParams, Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, ChevronDown, ExternalLink, Package, Star, Download, Tag, FileBox, Globe, Images, Box, ImagePlus, Pencil, Plus, Wrench, FolderDown, Folder, Copy, Check, Printer, Layers, Split, FolderOpen, X, ZoomIn, Paintbrush, RefreshCw, ImageOff, Bookmark, BookmarkCheck, Link2, Unlink2 } from "lucide-react";
import { api, ApiError, Model, ModelDetail as ModelDetailType, Collection } from "../api/client";
import FindOnWeb from "../components/FindOnWeb";
const STLViewer = lazy(() => import("../components/STLViewer"));
import ImagePicker from "../components/ImagePicker";
import MetadataEditor from "../components/MetadataEditor";
import KitBuilder from "../components/KitBuilder";
import StarRating from "../components/StarRating";
import TagInput from "../components/TagInput";
import { useNSFW } from "../context/NSFWContext";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";

function CollectionsSection({ modelId, initialIds }: { modelId: number; initialIds: number[] }) {
  const { toast } = useToast();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [memberIds, setMemberIds] = useState<Set<number>>(new Set(initialIds));
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    api.collections.list().then(setCollections).catch(() => {});
  }, []);

  const toggle = async (col: Collection) => {
    const isMember = memberIds.has(col.id);
    setMemberIds((prev) => {
      const next = new Set(prev);
      isMember ? next.delete(col.id) : next.add(col.id);
      return next;
    });
    try {
      if (isMember) {
        await api.collections.removeModel(col.id, modelId);
      } else {
        await api.collections.addModel(col.id, modelId);
      }
    } catch {
      setMemberIds((prev) => {
        const next = new Set(prev);
        isMember ? next.add(col.id) : next.delete(col.id);
        return next;
      });
      toast("Couldn't update collection — try again.", "error");
    }
  };

  const createAndAdd = async () => {
    if (!newName.trim()) return;
    try {
      const col = await api.collections.create(newName.trim());
      await api.collections.addModel(col.id, modelId);
      setCollections((prev) => [...prev, { ...col, model_count: 1 }]);
      setMemberIds((prev) => new Set([...prev, col.id]));
      setNewName("");
      setCreating(false);
    } catch {
      toast("Couldn't create collection — try again.", "error");
    }
  };

  const memberCollections = collections.filter((c) => memberIds.has(c.id));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          <FolderOpen size={14} />
          Collections
        </h3>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-xs text-gray-500 hover:text-indigo-400 transition-colors"
        >
          {open ? "Done" : "Manage"}
        </button>
      </div>

      {memberCollections.length === 0 && !open && (
        <p className="text-xs text-gray-600">Not in any collections</p>
      )}

      {memberCollections.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {memberCollections.map((c) => (
            <Link
              key={c.id}
              to={`/collections/${c.id}`}
              className="text-xs bg-indigo-950 border border-indigo-800 text-indigo-300 hover:bg-indigo-900 px-2 py-0.5 rounded-full transition-colors"
            >
              {c.name}
            </Link>
          ))}
        </div>
      )}

      {open && (
        <div className="flex flex-col gap-1 bg-gray-900 border border-gray-800 rounded-lg p-2">
          {collections.map((c) => (
            <button
              key={c.id}
              onClick={() => toggle(c)}
              className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800 text-sm text-left transition-colors"
            >
              <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                memberIds.has(c.id)
                  ? "bg-indigo-600 border-indigo-500"
                  : "border-gray-600"
              }`}>
                {memberIds.has(c.id) && <Check size={10} className="text-white" strokeWidth={3} />}
              </span>
              <span className="text-gray-200 truncate">{c.name}</span>
              <span className="text-xs text-gray-600 ml-auto">{c.model_count}</span>
            </button>
          ))}
          {collections.length === 0 && (
            <p className="text-xs text-gray-600 px-2 py-1">No collections yet</p>
          )}
          {creating ? (
            <div className="flex gap-1 mt-1 px-1">
              <input
                autoFocus
                type="text"
                placeholder="Collection name…"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createAndAdd()}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:outline-none focus:border-indigo-500"
              />
              <button onClick={createAndAdd} className="px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs">Create</button>
              <button onClick={() => setCreating(false)} className="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-400">Cancel</button>
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="flex items-center gap-1.5 px-2 py-1.5 rounded hover:bg-gray-800 text-xs text-gray-500 hover:text-indigo-400 transition-colors mt-0.5"
            >
              <Plus size={12} /> New collection
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const PART_TYPE_SUGGESTIONS = [
  "Head", "Torso", "Body",
  "Right Arm", "Left Arm", "Arms",
  "Right Leg", "Left Leg", "Legs",
  "Hands", "Feet", "Base",
  "Weapon", "Shield", "Cloak", "Cape",
  "Hair", "Wings", "Tail", "Accessories",
];

const toPascalCase = (s: string): string =>
  s.trim().split(/\s+/).filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");

function autoPartName(filename: string): string {
  return filename
    .replace(/\.(stl|STL)$/, "")
    .replace(/^Sup_/i, "")
    .replace(/_/g, " ")
    .trim();
}

const ALPHA_BANDS = [
  ["A", "D"], ["E", "H"], ["I", "L"], ["M", "P"], ["Q", "T"], ["U", "Z"],
] as const;

function buildAlphaBand(first: string): string {
  const u = first.toUpperCase();
  if (/[0-9]/.test(u)) return "0–9";
  for (const [start, end] of ALPHA_BANDS) {
    if (u >= start && u <= end) return `${start}–${end}`;
  }
  return "#";
}

function groupAlphabetically<T extends { id: number; filename: string }>(files: T[]): Array<[string, T[]]> {
  const order = [...ALPHA_BANDS.map(([s, e]) => `${s}–${e}`), "0–9", "#"];
  const map = new Map<string, T[]>();
  for (const f of files) {
    const band = buildAlphaBand(f.filename[0] ?? "");
    if (!map.has(band)) map.set(band, []);
    map.get(band)!.push(f);
  }
  return [...map.entries()]
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
}

type FileEntry<T> = { file: T; depth: 0 | 1 };

function buildFileHierarchy<T extends { id: number; filename: string; sup_of_id?: number | null }>(
  files: T[]
): FileEntry<T>[] {
  const supIds = new Set(files.filter((f) => f.sup_of_id != null).map((f) => f.id));
  const result: FileEntry<T>[] = [];
  for (const f of files.filter((f) => !supIds.has(f.id)).sort((a, b) => a.filename.localeCompare(b.filename))) {
    result.push({ file: f, depth: 0 });
    const sups = files.filter((s) => s.sup_of_id === f.id).sort((a, b) => a.filename.localeCompare(b.filename));
    for (const sup of sups) result.push({ file: sup, depth: 1 });
  }
  // Orphaned sup files (parent not in this group) fall through as top-level.
  for (const f of files.filter((f) => supIds.has(f.id))) {
    if (!result.find((r) => r.file.id === f.id)) result.push({ file: f, depth: 0 });
  }
  return result;
}

type ViewMode = "images" | "3d";

type NavTarget = { id: number; from: string };

// Parse a Library origin URL into the filter params needed for the neighbors
// endpoint. Returns null when the origin isn't the Library grid (path "/") —
// models reached from a variant group, collection, or deep link show no Prev/Next.
function parseLibraryOrigin(from: string | undefined): Record<string, string | number | boolean> | null {
  if (!from) return null;
  const [path, search = ""] = from.split("?");
  if (path !== "/") return null;
  const sp = new URLSearchParams(search);
  const params: Record<string, string | number | boolean> = {};
  for (const key of ["q", "creator_id", "exclude_creator_id", "source_site", "tag", "exclude_tag"]) {
    const val = sp.get(key);
    if (val) params[key] = val;
  }
  if (sp.get("needs_review") === "1") params.needs_review = true;
  // nsfw and has_thumbnail are tri-state: "1"=true, "0"=false, absent=no filter
  for (const key of ["nsfw", "has_thumbnail"]) {
    const val = sp.get(key);
    if (val === "1") params[key] = true;
    else if (val === "0") params[key] = false;
  }
  const fav = sp.get("is_favorite") === "1";
  const printStatus = sp.get("print_status") ?? "";
  const excludePrinted = sp.get("exclude_printed") === "1";
  const excluded = sp.get("excluded") === "1";
  const inbox = sp.get("is_inbox") === "1";
  if (fav) params.is_favorite = true;
  if (printStatus) params.print_status = printStatus;
  if (excludePrinted) params.exclude_printed = true;
  if (excluded) params.excluded = true;
  if (inbox) params.is_inbox = true;
  // "Recently added" view (#170): same window + newest-first order as the grid,
  // so Prev/Next walks the list the user was looking at.
  const addedDays = sp.get("added_days");
  if (addedDays) {
    params.added_within_days = addedDays;
    params.sort = "added";
  } else if (sp.get("sort")) {
    // Chosen Library sort (#247): walk Prev/Next in the same order as the grid.
    params.sort = sp.get("sort")!;
  }
  params.group_variants = !fav && !printStatus && !excluded;
  return params;
}

export default function ModelDetail() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const rawFrom = (location.state as any)?.from as string | undefined;
  const backTo = rawFrom ?? "/";
  const navOrigin = useMemo(() => parseLibraryOrigin(rawFrom), [rawFrom]); // null = not from Library → hide Prev/Next
  const { showNSFW } = useNSFW();
  const { settings } = useAppSettings();
  const { toast } = useToast();
  const confirm = useConfirm();
  // The painting guide for this model, if one exists (#263). null = none/unknown.
  const [guideId, setGuideId] = useState<number | null>(null);
  const [model, setModel] = useState<ModelDetailType | null>(null);
  // null = no error; "notfound" = 404 (model gone); "network" = transient
  // fetch/5xx failure the user can retry.
  const [loadError, setLoadError] = useState<"notfound" | "network" | null>(null);
  const [variants, setVariants] = useState<Model[]>([]);
  // Bumped on every load() so the variants effect refetches after in-place
  // refreshes (e.g. thumbnail updates) that don't change creator/character.
  const [variantVersion, setVariantVersion] = useState(0);
  const [loading, setLoading] = useState(true);
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
  const [printStatus, setPrintStatus] = useState<import("../api/client").PrintStatus>("none");
  const [printCount, setPrintCount] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [removedAutoTags, setRemovedAutoTags] = useState<string[]>([]);
  const [showHiddenTags, setShowHiddenTags] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [tagSuggestions, setTagSuggestions] = useState<{ tag: string; count: number }[]>([]);
  const [partTypes, setPartTypes] = useState<Record<number, string>>({});
  const [partNames, setPartNames] = useState<Record<number, string>>({});
  const [filesCollapsed, setFilesCollapsed] = useState<Set<string>>(new Set());
  const [hTableCollapsed, setHTableCollapsed] = useState<Set<string>>(new Set());
  const [linkingBaseId, setLinkingBaseId] = useState<number | null>(null);
  const [showKitBuilder, setShowKitBuilder] = useState(false);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [copiedPath, setCopiedPath] = useState(false);
  const [openFolderError, setOpenFolderError] = useState<string | null>(null);
  const [splitting, setSplitting] = useState(false);
  const [settingGroup, setSettingGroup] = useState(false);
  const [groupInput, setGroupInput] = useState("");
  const [savingGroup, setSavingGroup] = useState(false);
  const [groupSuggestions, setGroupSuggestions] = useState<string[]>([]);
  // undefined = loading, null = boundary/unavailable, NavTarget = navigable
  const [prevNav, setPrevNav] = useState<NavTarget | null | undefined>(undefined);
  const [nextNav, setNextNav] = useState<NavTarget | null | undefined>(undefined);
  const navFetchIdRef = useRef(0);
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
      const hasGallery = (model?.image_paths ?? []).length > 0;
      if (hasGallery) {
        const total = model!.image_paths.length;
        if (e.key === "ArrowLeft" && galleryIdx > 0) rotatorRef.current?.goTo(galleryIdx - 1);
        if (e.key === "ArrowRight" && galleryIdx < total - 1) rotatorRef.current?.goTo(galleryIdx + 1);
      } else {
        if (!activeImage) return;
        const allImgs = [
          model?.thumbnail_path ? api.fileUrl(model.thumbnail_path, model.updated_at) : model?.thumbnail_url,
          ...(model?.image_paths ?? []).map((p) => api.fileUrl(p)),
        ].filter(Boolean) as string[];
        const idx = allImgs.indexOf(activeImage);
        if (e.key === "ArrowLeft" && idx > 0) setActiveImage(allImgs[idx - 1]);
        if (e.key === "ArrowRight" && idx < allImgs.length - 1) setActiveImage(allImgs[idx + 1]);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [lightboxOpen, activeImage, galleryIdx, model]);

  // sync local state from loaded model
  useEffect(() => {
    if (model) {
      setNsfw(model.nsfw);
      setFavorite(model.is_favorite);
      setRating(model.user_rating ?? null);
      setPrintStatus(model.print_status ?? "none");
      setPrintCount(model.print_count ?? 0);
      setTags(model.tags ?? []);
      setRemovedAutoTags(model.removed_auto_tags ?? []);
      const pts: Record<number, string> = {};
      model.stl_files.forEach((f) => { if (f.part_type) pts[f.id] = toPascalCase(f.part_type); });
      setPartTypes(pts);
      const pns: Record<number, string> = {};
      model.stl_files.forEach((f) => { if (f.part_name) pns[f.id] = f.part_name; });
      setPartNames(pns);
    }
  }, [model]);

  // When the viewer selects a file, uncollapse its section in the file list and scroll to it.
  useEffect(() => {
    if (!selectedStlFileId || !model) return;
    const file = model.stl_files.find((f) => f.id === selectedStlFileId);
    if (!file) return;
    const sectionKey = settings.part_categories_enabled
      ? (file.part_type ? toPascalCase(file.part_type) : "__uncategorized__")
      : buildAlphaBand(file.filename[0]?.toUpperCase() ?? "");
    setFilesCollapsed((prev) => { const n = new Set(prev); n.delete(sectionKey); return n; });
    requestAnimationFrame(() => {
      document.querySelector(`[data-file-row="${selectedStlFileId}"]`)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }, [selectedStlFileId]);

  // Reset UI-only state when navigating to a different model
  useEffect(() => {
    setEditing(false);
    setShowFindOnWeb(false);
    setShowImagePicker(false);
    setShowKitBuilder(false);
    setOpenFolderError(null);
    setSettingGroup(false);
    setShowHiddenTags(false);
    setEditingTags(false);
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
    } catch (e: any) {
      toast(e?.message || "Couldn't split this model — try again.", "error");
      setSplitting(false);
    }
  };

  const openSetGroup = () => {
    setGroupInput(model?.character ?? "");
    setSettingGroup(true);
    if (model?.creator_id) {
      api.models.characters(model.creator_id).then(setGroupSuggestions).catch(() => {});
    }
  };

  const saveGroup = async () => {
    if (!model || savingGroup) return;
    setSavingGroup(true);
    try {
      const trimmed = groupInput.trim();
      await api.models.setGroupOverride(model.id, trimmed || null);
      toast(trimmed ? `Moved to group "${trimmed}".` : "Removed from group.", "success");
      setSettingGroup(false);
      load();
    } catch (e: any) {
      toast(e?.message || "Couldn't save group — try again.", "error");
    } finally {
      setSavingGroup(false);
    }
  };

  const clearGroup = async () => {
    if (!model) return;
    const ok = await confirm({
      title: "Clear the group override?",
      message: "The model will return to its scanner-detected group on the next rescan.",
      confirmLabel: "Clear override",
    });
    if (!ok) return;
    try {
      await api.models.clearGroupOverride(model.id);
      toast("Group override cleared — rescan to apply heuristic.", "success");
      load();
    } catch (e: any) {
      toast(e?.message || "Couldn't clear override — try again.", "error");
    }
  };

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
    } catch (e: any) {
      toast(e?.message || "Couldn't clear the image — try again.", "error");
    }
  };

  const savePartType = async (fileId: number, value: string) => {
    const pt = toPascalCase(value);
    // Always normalise the displayed value to Pascal case, even if no save is needed.
    const thisFile = model?.stl_files.find((f) => f.id === fileId);
    const saved = thisFile?.part_type ?? "";
    setPartTypes((prevState) => ({ ...prevState, [fileId]: pt }));

    // Find ALL linked files: sups of this file (if base) + base of this file (if sup) + sibling sups.
    const linkedFiles: NonNullable<typeof model>["stl_files"] = [];
    if (thisFile) {
      const directSups = model?.stl_files.filter((f) => f.sup_of_id === fileId) ?? [];
      linkedFiles.push(...directSups);
      if (thisFile.sup_of_id != null) {
        const base = model?.stl_files.find((f) => f.id === thisFile.sup_of_id);
        if (base) {
          linkedFiles.push(base);
          const siblings = model?.stl_files.filter((f) => f.sup_of_id === base.id && f.id !== fileId) ?? [];
          linkedFiles.push(...siblings);
        }
      }
      // Filename fallback when no explicit sup_of_id relationship exists.
      if (linkedFiles.length === 0) {
        const counterpartName = /^Sup_/i.test(thisFile.filename)
          ? thisFile.filename.replace(/^Sup_/i, "")
          : `Sup_${thisFile.filename}`;
        const counterpart = model?.stl_files.find((f) => f.filename === counterpartName) ?? null;
        if (counterpart) linkedFiles.push(counterpart);
      }
    }

    const linkedNeedingUpdate = linkedFiles.filter((p) => p.part_type !== (pt || null));
    const thisNeedsUpdate = pt !== saved;
    if (!thisNeedsUpdate && linkedNeedingUpdate.length === 0) return;

    try {
      if (thisNeedsUpdate) {
        await api.models.updateSTLFile(fileId, { part_type: pt || null });
        setModel((prev) =>
          prev
            ? { ...prev, stl_files: prev.stl_files.map((f) => f.id === fileId ? { ...f, part_type: pt || null } : f) }
            : prev
        );
      }
      for (const paired of linkedNeedingUpdate) {
        setPartTypes((prevState) => ({ ...prevState, [paired.id]: pt }));
        await api.models.updateSTLFile(paired.id, { part_type: pt || null });
        setModel((prev) =>
          prev
            ? { ...prev, stl_files: prev.stl_files.map((f) => f.id === paired.id ? { ...f, part_type: pt || null } : f) }
            : prev
        );
      }
    } catch {
      setPartTypes((prevState) => ({ ...prevState, [fileId]: saved }));
      toast("Couldn't save category — try again.", "error");
    }
  };

  const patchStlFile = (fileId: number, patch: Partial<{ sup_of_id: number | null; part_type: string | null; part_name: string | null }>) =>
    setModel((prev) =>
      prev ? { ...prev, stl_files: prev.stl_files.map((f) => f.id === fileId ? { ...f, ...patch } : f) } : prev
    );

  const savePartName = async (fileId: number, value: string) => {
    const trimmed = value.trim() || null;
    try {
      await api.models.updateSTLFile(fileId, { part_name: trimmed });
      patchStlFile(fileId, { part_name: trimmed });
    } catch {
      toast("Couldn't save name — try again.", "error");
    }
  };

  const linkSup = async (baseId: number, supId: number) => {
    try {
      await api.models.updateSTLFile(supId, { sup_of_id: baseId });
      patchStlFile(supId, { sup_of_id: baseId });
      // Sync the base file's category to the newly linked sup file so they
      // appear in the same group and render as a hierarchy.
      const basePt = partTypes[baseId] ?? model?.stl_files.find((f) => f.id === baseId)?.part_type ?? null;
      if (basePt) {
        const pt = toPascalCase(basePt);
        await api.models.updateSTLFile(supId, { part_type: pt });
        patchStlFile(supId, { part_type: pt });
        setPartTypes((prev) => ({ ...prev, [supId]: pt }));
      }
    } catch {
      toast("Couldn't link files — try again.", "error");
    }
  };

  const unlinkSup = async (supId: number) => {
    try {
      await api.models.updateSTLFile(supId, { sup_of_id: null });
      patchStlFile(supId, { sup_of_id: null });
    } catch {
      toast("Couldn't unlink file — try again.", "error");
    }
  };

  const addTag = async (tag: string) => {
    if (tags.includes(tag)) return;
    const prev = tags;
    const next = [...tags, tag];
    setTags(next);
    try {
      await api.models.update(Number(id), { tags: next });
    } catch {
      setTags(prev);  // revert on failure
      toast("Couldn't add tag — try again.", "error");
    }
  };

  // Replace the full user-tag set (inline editor add/remove). Optimistic with
  // revert, mirroring addTag.
  const setUserTags = async (next: string[]) => {
    const prev = tags;
    setTags(next);
    try {
      await api.models.update(Number(id), { tags: next });
    } catch {
      setTags(prev);  // revert on failure
      toast("Couldn't update tags — try again.", "error");
    }
  };

  // Open the inline tag editor, lazily loading tag suggestions on first use.
  const openTagEditor = () => {
    setEditingTags(true);
    if (tagSuggestions.length === 0) {
      api.models.tags().then(setTagSuggestions).catch(() => {});
    }
  };

  // Suppress an auto-detected tag so it stops showing and survives rescans.
  // If it was already promoted to a user tag, drop that too.
  const suppressAutoTag = async (tag: string) => {
    const prevRemoved = removedAutoTags;
    const prevTags = tags;
    const nextRemoved = removedAutoTags.includes(tag) ? removedAutoTags : [...removedAutoTags, tag];
    const nextTags = tags.filter((t) => t !== tag);
    setRemovedAutoTags(nextRemoved);
    setTags(nextTags);
    try {
      await api.models.update(Number(id), { removed_auto_tags: nextRemoved, tags: nextTags });
    } catch {
      setRemovedAutoTags(prevRemoved);  // revert on failure
      setTags(prevTags);
      toast("Couldn't remove tag — try again.", "error");
    }
  };

  // Un-suppress a previously removed auto-tag so it reappears as auto-detected.
  const restoreAutoTag = async (tag: string) => {
    const prevRemoved = removedAutoTags;
    const nextRemoved = removedAutoTags.filter((t) => t !== tag);
    setRemovedAutoTags(nextRemoved);
    try {
      await api.models.update(Number(id), { removed_auto_tags: nextRemoved });
    } catch {
      setRemovedAutoTags(prevRemoved);  // revert on failure
      toast("Couldn't restore tag — try again.", "error");
    }
  };

  const toggleNSFW = async () => {
    const next = !nsfw;
    setNsfw(next);
    try {
      await api.models.setNSFW(Number(id), next);
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
    } catch {
      setRating(prev);  // revert on failure
      toast("Couldn't update rating — try again.", "error");
    }
  };

  const cyclePrintStatus = async () => {
    const { PRINT_STATUS_CYCLE } = await import("../api/client");
    const idx = PRINT_STATUS_CYCLE.indexOf(printStatus);
    const next = PRINT_STATUS_CYCLE[(idx + 1) % PRINT_STATUS_CYCLE.length];
    const prev = printStatus;
    const prevCount = printCount;
    setPrintStatus(next);
    try {
      const res = await api.models.setPrintStatus(Number(id), next);
      setPrintCount(res.print_count);
    } catch {
      setPrintStatus(prev);
      setPrintCount(prevCount);
      toast("Couldn't update print status — try again.", "error");
    }
  };

  const clearPrintStatus = async () => {
    const prev = printStatus;
    const prevCount = printCount;
    setPrintStatus("none");
    try {
      const res = await api.models.setPrintStatus(Number(id), "none");
      setPrintCount(res.print_count);
    } catch {
      setPrintStatus(prev);
      setPrintCount(prevCount);
      toast("Couldn't clear print status — try again.", "error");
    }
  };

  const loadIdRef = useRef(0);
  const load = useCallback(() => {
    if (!id) return;
    const loadId = ++loadIdRef.current;
    setLoadError(null);
    api.models.get(Number(id)).then((m) => {
      if (loadId !== loadIdRef.current) return; // stale — newer load in flight
      setModel(m);
      setVariantVersion((v) => v + 1);
      const thumb = m.thumbnail_path
        ? api.fileUrl(m.thumbnail_path, m.updated_at)
        : m.thumbnail_url ?? null;
      setActiveImage(thumb);
      setLoading(false);
    }).catch((err) => {
      if (loadId !== loadIdRef.current) return;
      // A 404 means the model is genuinely gone; anything else (network drop,
      // 5xx) is transient and worth a retry rather than "not found".
      setLoadError(err instanceof ApiError && err.status === 404 ? "notfound" : "network");
      setLoading(false);
    });
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Resolve whether this model has a painting guide (#263), gated on the module.
  useEffect(() => {
    if (!settings.painting_guides_enabled || !id) { setGuideId(null); return; }
    let alive = true;
    api.painting.guides.list({ model_id: Number(id), page_size: 1 })
      .then((r) => { if (alive) setGuideId(r.items[0]?.id ?? null); })
      .catch(() => { if (alive) setGuideId(null); });
    return () => { alive = false; };
  }, [id, settings.painting_guides_enabled]);

  // Show the loading state when switching to a different model so the previous
  // model's data (collections, tags, etc.) never bleeds into the new view while
  // the fetch is in flight. Keyed on id only, so in-place refreshes that call
  // load() directly (after edits) don't flash a full loading screen.
  useEffect(() => { setLoading(true); }, [id]);

  // Fetch sibling variants for the variant switcher. Keyed on the (creator,
  // character) group plus a version counter bumped by load(), so in-place
  // refreshes (thumbnail capture/picker, metadata save) update the switcher
  // thumbnails even though creator/character are unchanged.
  useEffect(() => {
    if (model?.creator_id && model.character) {
      api.models
        .variants(model.creator_id, model.character)
        .then((data) => setVariants(data.items))
        .catch(() => setVariants([]));
    } else {
      setVariants([]);
    }
  }, [model?.creator_id, model?.character, variantVersion]);

  useEffect(() => {
    if (!navOrigin || !id) {
      setPrevNav(null);
      setNextNav(null);
      return;
    }
    const currentId = Number(id);
    const navId = ++navFetchIdRef.current;
    setPrevNav(undefined);
    setNextNav(undefined);

    api.models.neighbors(currentId, navOrigin)
      .then((data) => {
        if (navId !== navFetchIdRef.current) return;
        setPrevNav(data.prev_id != null ? { id: data.prev_id, from: backTo } : null);
        setNextNav(data.next_id != null ? { id: data.next_id, from: backTo } : null);
      })
      .catch(() => {
        if (navId !== navFetchIdRef.current) return;
        setPrevNav(null);
        setNextNav(null);
      });
  }, [id, backTo, navOrigin]);

  if (loading) return <div className="p-8 text-gray-500 animate-pulse">Loading…</div>;
  if (loadError === "network") {
    return (
      <div className="p-8 flex flex-col items-start gap-3 text-gray-400">
        <p>Couldn't load this model — check your connection and try again.</p>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-sm text-white transition-colors"
        >
          <RefreshCw size={14} /> Retry
        </button>
      </div>
    );
  }
  if (!model) return <div className="p-8 text-gray-500">Model not found.</div>;

  const allImages = [
    model.thumbnail_path ? api.fileUrl(model.thumbnail_path, model.updated_at) : model.thumbnail_url,
    ...model.image_paths.map((p) => api.fileUrl(p)),
  ].filter(Boolean) as string[];

  const hasSTLs = model.stl_files.some((f) =>
    f.filename.toLowerCase().endsWith(".stl")
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <Link to={backTo} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 w-fit">
          <ArrowLeft size={14} /> Back to Library
        </Link>

        {navOrigin && (
          <div className="flex items-center gap-1">
            {prevNav !== undefined ? (
              prevNav !== null ? (
                <Link
                  to={`/models/${prevNav.id}`}
                  state={{ from: prevNav.from }}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-gray-100 hover:bg-gray-800 transition-colors"
                >
                  <ChevronLeft size={15} /> Prev
                </Link>
              ) : (
                <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-gray-700 cursor-default select-none">
                  <ChevronLeft size={15} /> Prev
                </span>
              )
            ) : (
              <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-gray-700 animate-pulse select-none">
                <ChevronLeft size={15} /> Prev
              </span>
            )}

            {nextNav !== undefined ? (
              nextNav !== null ? (
                <Link
                  to={`/models/${nextNav.id}`}
                  state={{ from: nextNav.from }}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-gray-100 hover:bg-gray-800 transition-colors"
                >
                  Next <ChevronRight size={15} />
                </Link>
              ) : (
                <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-gray-700 cursor-default select-none">
                  Next <ChevronRight size={15} />
                </span>
              )
            ) : (
              <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm text-gray-700 animate-pulse select-none">
                Next <ChevronRight size={15} />
              </span>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        {/* Left column — Images / 3D viewer */}
        <div className="flex flex-col gap-3">

          {/* View mode toggle */}
          {hasSTLs && (
            <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1 self-start">
              <button
                onClick={() => setViewMode("images")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === "images"
                    ? "bg-gray-700 text-gray-100"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                <Images size={14} /> Images
              </button>
              <button
                onClick={() => setViewMode("3d")}
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
                    onIndexChange={setGalleryIdx}
                  />
                ) : activeImage ? (
                  <img
                    src={activeImage}
                    alt={model.title ?? model.name}
                    onClick={() => setLightboxOpen(true)}
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
                    onClick={() => setLightboxOpen(true)}
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
                              if (!ok) return;
                              const newPaths = model.image_paths.filter((_, i) => i !== galleryIdx);
                              await api.models.update(model.id, { image_paths: newPaths });
                              load();
                            }}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-rose-900/70 text-gray-300 hover:text-white text-xs"
                          >
                            <ImageOff size={13} /> Delete image
                          </button>
                          {isPrimary ? (
                            <button
                              onClick={async () => {
                                await api.models.update(model.id, { primary_image_path: null });
                                load();
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
                                load();
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
                          onClick={clearImage}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-rose-900/70 text-gray-300 hover:text-white text-xs"
                        >
                          <ImageOff size={13} /> Clear image
                        </button>
                      )}
                      <button
                        onClick={() => setShowImagePicker(true)}
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
                const totalItems = (thumbSrc ? 1 : 0) + model.image_paths.length;
                if (totalItems <= 1) return null;
                return (
                  <div className="flex gap-2 flex-wrap">
                    {thumbSrc && (
                      <button
                        onClick={() => setActiveImage(thumbSrc)}
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
                onThumbnailCaptured={load}
                categoriesEnabled={settings.part_categories_enabled}
                selectedFileId={selectedStlFileId ?? undefined}
                onSelectFile={setSelectedStlFileId}
                hidePicker={settings.horizontal_parts_layout}
              />
            </Suspense>
          )}
        </div>

        {/* Right column — Info */}
        <div className="flex flex-col gap-4">
          {/* Title above the action row — side-by-side overlapped on long names (#187) */}
          <div className="flex flex-col gap-3">
            <div className="min-w-0">
              {model.character && (
                <p className="text-sm text-indigo-400 mb-1">{model.character}</p>
              )}
              <h1 className="text-2xl font-bold text-gray-100 break-words">{model.title || model.name}</h1>
              {model.creator && (
                <p className="text-gray-400 mt-1">by {model.creator.name}</p>
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
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                <Star size={14} fill={favorite ? "currentColor" : "none"} />
                Favorite
              </button>
              <div
                className="flex items-center gap-1 px-2 py-1 rounded border bg-gray-800 border-gray-700"
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
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
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
                  className="px-2 py-1.5 rounded border border-gray-700 bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors"
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
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                {nsfw ? "NSFW ✓" : "NSFW"}
              </button>
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-indigo-500 text-sm text-gray-300 transition-colors"
              >
                <Pencil size={14} />
                Edit
              </button>
              <button
                onClick={() => setShowFindOnWeb(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-indigo-500 text-sm text-gray-300 transition-colors"
              >
                <Globe size={14} />
                Find on Web
              </button>
              <button
                onClick={splitPack}
                disabled={splitting}
                title="If this folder is actually a pack of separate models, split it into one model per sub-folder"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-indigo-500 text-sm text-gray-300 transition-colors disabled:opacity-40"
              >
                <Split size={14} />
                {splitting ? "Splitting…" : "Split pack"}
              </button>
              {model.has_group_override ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={openSetGroup}
                    title="Change the group this model belongs to"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-900/50 hover:bg-indigo-800/60 border border-indigo-700 text-sm text-indigo-300 transition-colors"
                  >
                    <Tag size={14} />
                    Group: {model.character ?? "none"}
                  </button>
                  <button
                    onClick={clearGroup}
                    title="Remove override and restore scanner-detected grouping on next rescan"
                    className="px-2 py-1.5 rounded bg-gray-800 hover:bg-red-900/40 border border-gray-700 hover:border-red-600 text-xs text-gray-500 hover:text-red-400 transition-colors"
                  >
                    ✕
                  </button>
                </div>
              ) : (
                <button
                  onClick={openSetGroup}
                  title="Assign this model to a character group (persists across rescans)"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-indigo-500 text-sm text-gray-300 transition-colors"
                >
                  <Tag size={14} />
                  Set group
                </button>
              )}
            </div>
          </div>

          {/* ---- Set group inline form ---- */}
          {settingGroup && (
            <div className="flex items-center gap-2 px-1 py-2">
              <Tag size={14} className="text-indigo-400 shrink-0" />
              <input
                autoFocus
                type="text"
                list="group-suggestions"
                value={groupInput}
                onChange={(e) => setGroupInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveGroup(); if (e.key === "Escape") setSettingGroup(false); }}
                placeholder="Group name (leave blank to ungroup)"
                className="flex-1 px-2 py-1 rounded bg-gray-900 border border-gray-700 focus:border-indigo-500 text-sm text-gray-200 outline-none"
              />
              <datalist id="group-suggestions">
                {groupSuggestions.map((s) => <option key={s} value={s} />)}
              </datalist>
              <button
                onClick={saveGroup}
                disabled={savingGroup}
                className="px-3 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-sm text-white disabled:opacity-40"
              >
                {savingGroup ? "Saving…" : "Save"}
              </button>
              <button
                onClick={() => setSettingGroup(false)}
                className="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-sm text-gray-400"
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
          {variants.length > 1 && (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-gray-600 flex items-center gap-1.5">
                <Layers size={12} className="text-indigo-400" />
                {variants.length} variants of {model.character}
              </p>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {variants.map((v) => {
                  const vThumb = v.thumbnail_path
                    ? api.fileUrl(v.thumbnail_path, v.updated_at)
                    : v.thumbnail_url ?? null;
                  const isCurrent = v.id === model.id;
                  // For the current variant, reflect live local toggles rather
                  // than the (possibly stale) value from the variants fetch.
                  const vFavorite = isCurrent ? favorite : v.is_favorite;
                  const vQueued = (isCurrent ? printStatus : v.print_status) === "queued";
                  return (
                    <Link
                      key={v.id}
                      to={`/models/${v.id}`}
                      state={{ from: backTo }}
                      title={v.title || v.name}
                      className={`relative shrink-0 w-20 rounded-lg overflow-hidden border-2 transition-colors ${
                        isCurrent
                          ? "border-indigo-500"
                          : "border-gray-800 hover:border-gray-600"
                      }`}
                    >
                      <div className="aspect-square bg-gray-800">
                        {vThumb ? (
                          <img src={vThumb} alt="" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-gray-700">
                            <Package size={20} />
                          </div>
                        )}
                      </div>
                      {(vFavorite || vQueued) && (
                        <div className="absolute top-1 right-1 flex gap-0.5">
                          {vQueued && (
                            <span className="bg-black/70 rounded p-0.5 text-sky-400">
                              <Printer size={9} />
                            </span>
                          )}
                          {vFavorite && (
                            <span className="bg-black/70 rounded p-0.5 text-yellow-400">
                              <Star size={9} fill="currentColor" />
                            </span>
                          )}
                        </div>
                      )}
                      <p className="px-1 py-0.5 text-[10px] leading-tight text-gray-400 truncate">
                        {v.title || v.name}
                      </p>
                    </Link>
                  );
                })}
              </div>
            </div>
          )}

          {/* Stats row */}
          <div className="flex items-center gap-4 text-sm text-gray-400">
            {model.rating != null && (
              <span className="flex items-center gap-1 text-yellow-400">
                <Star size={14} fill="currentColor" />
                {model.rating.toLocaleString()}
              </span>
            )}
            {model.download_count != null && (
              <span className="flex items-center gap-1">
                <Download size={14} />
                {model.download_count.toLocaleString()}
              </span>
            )}
            {model.source_site && (
              <span className="capitalize bg-gray-800 px-2 py-0.5 rounded text-xs">
                {model.source_site}
              </span>
            )}
            {model.license && (
              <span className="bg-gray-800 px-2 py-0.5 rounded text-xs">{model.license}</span>
            )}
          </div>

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
            <p className="text-sm text-gray-400 leading-relaxed whitespace-pre-line line-clamp-6">
              {model.description}
            </p>
          )}

          {/* User tags — chips browse by tag; inline editor adds/removes
              without opening the full edit screen (#411) */}
          {editingTags ? (
            <div className="flex flex-col gap-1.5">
              <TagInput
                value={tags}
                onChange={setUserTags}
                suggestions={tagSuggestions}
              />
              <button
                onClick={() => setEditingTags(false)}
                className="text-xs text-gray-500 hover:text-gray-300 w-fit"
              >
                Done
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-1.5">
              {tags.map((tag) => (
                <Link
                  key={tag}
                  to={`/?tag=${encodeURIComponent(tag)}`}
                  className="flex items-center gap-1 text-xs bg-gray-800 text-gray-400 hover:bg-indigo-950 hover:text-indigo-300 hover:border-indigo-700 border border-transparent px-2 py-1 rounded-full transition-colors"
                >
                  <Tag size={10} />
                  {tag}
                </Link>
              ))}
              <button
                onClick={openTagEditor}
                title="Add or remove tags"
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-indigo-300 border border-dashed border-gray-700 hover:border-indigo-700 px-2 py-1 rounded-full transition-colors"
              >
                <Plus size={10} />
                {tags.length > 0 ? "Edit tags" : "Add tag"}
              </button>
            </div>
          )}

          {/* Auto-detected tags — click + to promote to a user tag, × to remove
              (suppressed tags survive rescans), click label to browse */}
          {(() => {
            const visibleAutoTags = (model.auto_tags ?? []).filter(
              (t) => !removedAutoTags.includes(t)
            );
            if (visibleAutoTags.length === 0) return null;
            return (
            <div className="flex flex-col gap-1.5">
              <p className="text-xs text-gray-600">Auto-detected · click + to add as tag · × to remove · click label to browse</p>
              <div className="flex flex-wrap gap-1.5">
                {visibleAutoTags.map((tag) => {
                  const already = tags.includes(tag);
                  return (
                    <div key={tag} className="flex items-center rounded-full border overflow-hidden border-gray-700">
                      <button
                        onClick={() => addTag(tag)}
                        disabled={already}
                        title={already ? "Already a tag" : "Add as user tag"}
                        className={`flex items-center px-1.5 py-0.5 text-xs border-r border-gray-700 transition-colors ${
                          already
                            ? "bg-indigo-900/30 text-indigo-500 cursor-default"
                            : "bg-gray-800/60 text-gray-500 hover:bg-indigo-950 hover:text-indigo-400"
                        }`}
                      >
                        {already ? <Tag size={9} /> : <Plus size={9} />}
                      </button>
                      <Link
                        to={`/?tag=${encodeURIComponent(tag)}`}
                        className="flex items-center px-2 py-0.5 text-xs bg-gray-800/60 text-gray-500 hover:bg-indigo-950 hover:text-indigo-300 transition-colors"
                      >
                        {tag}
                      </Link>
                      <button
                        onClick={() => suppressAutoTag(tag)}
                        title="Remove this auto-detected tag"
                        className="flex items-center px-1.5 py-0.5 text-xs border-l border-gray-700 bg-gray-800/60 text-gray-600 hover:bg-rose-950 hover:text-rose-400 transition-colors"
                      >
                        <X size={9} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
            );
          })()}

          {/* Hidden (suppressed) auto-tags — restore any that the scanner still
              detects. Only shows tags currently in auto_tags so restoring is
              guaranteed to bring the chip back. */}
          {(() => {
            const hidden = (model.auto_tags ?? []).filter((t) => removedAutoTags.includes(t));
            if (hidden.length === 0) return null;
            return (
              <div className="flex flex-col gap-1.5">
                <button
                  onClick={() => setShowHiddenTags((s) => !s)}
                  className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 transition-colors w-fit"
                >
                  {showHiddenTags ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  {hidden.length} hidden auto-{hidden.length === 1 ? "tag" : "tags"}
                </button>
                {showHiddenTags && (
                  <div className="flex flex-wrap gap-1.5">
                    {hidden.map((tag) => (
                      <button
                        key={tag}
                        onClick={() => restoreAutoTag(tag)}
                        title="Restore this auto-detected tag"
                        className="flex items-center gap-1 rounded-full border border-gray-800 px-2 py-0.5 text-xs bg-gray-900/60 text-gray-600 line-through hover:no-underline hover:border-emerald-800 hover:bg-emerald-950 hover:text-emerald-400 transition-colors"
                      >
                        <Plus size={9} />
                        {tag}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Collections — always in right column */}
          <CollectionsSection key={model.id} modelId={model.id} initialIds={model.collection_ids} />

          {/* Location — in right column right under collections when horizontal layout */}
          {settings.horizontal_parts_layout && (
            <div>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5 mb-2">
                <Folder size={14} />
                Location
              </h3>
              <div className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
                <p className="text-xs text-gray-400 break-all font-mono leading-relaxed">
                  {model.native_folder_path || model.folder_path}
                </p>
                <div className="flex gap-2 mt-2">
                  <button onClick={copyPath} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors">
                    {copiedPath ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                    {copiedPath ? "Copied!" : "Copy path"}
                  </button>
                  <button onClick={openFolder} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors">
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
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5 mb-2">
                <FileBox size={14} />
                Other Files ({(model.other_files ?? []).length})
              </h3>
              <div className="space-y-1">
                {(model.other_files ?? []).map((fp) => {
                  const name = fp.split(/[\\/]/).pop() ?? fp;
                  return (
                    <a key={fp} href={api.documentUrl(fp)} download={name} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 hover:border-gray-600 hover:bg-gray-800 text-xs text-gray-300 hover:text-gray-100 transition-colors">
                      <FileBox size={12} className="shrink-0 text-gray-500" />
                      <span className="truncate">{name}</span>
                    </a>
                  );
                })}
              </div>
            </div>
          )}

          {/* STL Files list */}
          {!settings.horizontal_parts_layout && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                <FileBox size={14} />
                Files ({model.stl_files.length})
              </h3>
              {model.stl_files.length > 0 && (
                <div className="flex gap-2">
                  <button
                    onClick={downloadAllFiles}
                    disabled={downloadingAll}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-500 disabled:opacity-40 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                  >
                    <FolderDown size={12} />
                    {downloadingAll ? "Zipping…" : "Download all"}
                  </button>
                  <button
                    onClick={() => setShowKitBuilder(true)}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-indigo-950 border border-gray-700 hover:border-indigo-600 text-xs text-gray-400 hover:text-indigo-300 transition-colors"
                  >
                    <Wrench size={12} />
                    Kit Builder
                  </button>
                </div>
              )}
            </div>
            {/* Files list — hierarchical, with sup files indented below their base */}
            {(() => {
              // Determine which files are sups of which bases across the whole model.
              const supFileIds = new Set(model.stl_files.filter((f) => f.sup_of_id != null).map((f) => f.id));

              // Render a single file row (with hierarchy depth treatment).
              const renderRow = (f: typeof model.stl_files[0], depth: 0 | 1, withCategory: boolean) => {
                const isSup = depth === 1;
                const pt = partTypes[f.id] ?? "";
                const isBase = !isSup && !supFileIds.has(f.id);
                const isSelected = selectedStlFileId === f.id;

                return (
                  <div key={f.id} className="flex flex-col gap-0.5">
                    <div
                      data-file-row={f.id}
                      onClick={() => { setSelectedStlFileId(f.id); setViewMode("3d"); }}
                      className={`flex items-center gap-1.5 text-xs border px-2 py-1.5 rounded cursor-pointer transition-colors ${isSup ? "ml-4" : ""} ${isSelected ? "bg-indigo-950/40 border-indigo-500/60" : "bg-gray-900 border-gray-800 hover:border-gray-700"}`}
                    >
                      {/* Hierarchy indicator */}
                      {isSup && <span className="text-gray-600 shrink-0 select-none">↳</span>}

                      {/* Filename */}
                      <span className="text-gray-300 truncate flex-1 min-w-0" title={f.filename}>{f.filename}</span>

                      {/* Category input (categories mode only) */}
                      {withCategory && (
                        <input
                          list="part-category-list"
                          value={pt}
                          placeholder="Category…"
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => { const v = e.target.value; setPartTypes((prev) => ({ ...prev, [f.id]: toPascalCase(v) + (v.endsWith(" ") ? " " : "") })); }}
                          onBlur={(e) => savePartType(f.id, e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                          className="w-28 shrink-0 bg-gray-800 border border-gray-700 focus:border-indigo-500 rounded px-2 py-0.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none"
                        />
                      )}

                      {/* Size */}
                      {f.size_bytes ? (
                        <a href={api.stlUrl(f.path)} download={f.filename} onClick={(e) => e.stopPropagation()} className="text-gray-600 hover:text-gray-400 shrink-0 tabular-nums transition-colors w-14 text-right">
                          {(f.size_bytes / 1024 / 1024).toFixed(1)} MB
                        </a>
                      ) : <span className="w-14 shrink-0" />}

                      {/* Link / Unlink */}
                      {isSup ? (
                        <button
                          title="Remove supported-version link"
                          onClick={(e) => { e.stopPropagation(); unlinkSup(f.id); }}
                          className="shrink-0 text-gray-600 hover:text-rose-400 transition-colors"
                        >
                          <Unlink2 size={14} />
                        </button>
                      ) : isBase ? (
                        <button
                          title="Link a supported version"
                          onClick={(e) => { e.stopPropagation(); setLinkingBaseId(linkingBaseId === f.id ? null : f.id); }}
                          className={`shrink-0 transition-colors ${linkingBaseId === f.id ? "text-indigo-400" : "text-gray-600 hover:text-indigo-400"}`}
                        >
                          <Link2 size={14} />
                        </button>
                      ) : <span className="w-[11px] shrink-0" />}
                    </div>

                    {/* Inline sup-picker */}
                    {isBase && linkingBaseId === f.id && (
                      <div
                        className="ml-4 flex items-center gap-2 px-2 py-1.5 bg-gray-800 rounded border border-indigo-600/60"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Link2 size={14} className="text-indigo-400 shrink-0" />
                        <select
                          autoFocus
                          defaultValue=""
                          className="flex-1 min-w-0 bg-gray-700 text-xs text-gray-300 rounded px-1.5 py-0.5 border border-gray-600 focus:outline-none focus:border-indigo-500"
                          onChange={(e) => { if (e.target.value) { linkSup(f.id, parseInt(e.target.value)); setLinkingBaseId(null); } }}
                          onBlur={() => setLinkingBaseId(null)}
                        >
                          <option value="" disabled>Select supported-version file…</option>
                          {model.stl_files
                            .filter((sf) => sf.id !== f.id)
                            .sort((a, b) => a.filename.localeCompare(b.filename))
                            .map((sf) => {
                              const alreadyHere = sf.sup_of_id === f.id;
                              const linkedElsewhere = sf.sup_of_id != null && !alreadyHere;
                              return (
                                <option key={sf.id} value={sf.id} disabled={alreadyHere}>
                                  {sf.filename}{alreadyHere ? " ✓ (already this file's sup)" : linkedElsewhere ? " (linked to another)" : ""}
                                </option>
                              );
                            })}
                        </select>
                        <button onMouseDown={(e) => e.preventDefault()} onClick={() => setLinkingBaseId(null)} className="shrink-0 text-gray-500 hover:text-gray-300">
                          <X size={11} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              };

              // Render a group of files as a collapsible section.
              const renderSection = (
                key: string,
                header: React.ReactNode,
                files: typeof model.stl_files,
                withCategory: boolean,
                defaultOpen = true,
              ) => {
                const isCollapsed = filesCollapsed.has(key);
                const hierarchy = buildFileHierarchy(files);
                return (
                  <div key={key} className="flex flex-col gap-0.5">
                    <button
                      onClick={() => setFilesCollapsed((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; })}
                      className="w-full flex items-center justify-between px-2 py-1.5 rounded bg-gray-800/60 hover:bg-gray-800 border border-gray-700/50 text-left transition-colors"
                    >
                      {header}
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-600 tabular-nums">{files.length}</span>
                        {!isCollapsed ? <ChevronDown size={11} className="text-gray-600" /> : <ChevronRight size={11} className="text-gray-600" />}
                      </div>
                    </button>
                    {(defaultOpen ? !isCollapsed : !isCollapsed) && hierarchy.map(({ file: f, depth }) => renderRow(f, depth, withCategory))}
                  </div>
                );
              };

              return (
                <div className="flex flex-col gap-1 max-h-96 overflow-y-auto">
                  {settings.part_categories_enabled && (
                    <datalist id="part-category-list">
                      {PART_TYPE_SUGGESTIONS.map((s) => <option key={s} value={s} />)}
                    </datalist>
                  )}

                  {settings.part_categories_enabled ? (
                    <>
                      {groupedStlFiles.labeled.map(([cat, catFiles]) =>
                        renderSection(
                          cat,
                          <span className="text-xs font-medium text-gray-400">{toPascalCase(cat)}</span>,
                          catFiles,
                          true,
                        )
                      )}
                      {groupedStlFiles.unlabeled.length > 0 && renderSection(
                        "__uncategorized__",
                        <span className="text-xs font-medium text-gray-500">
                          Uncategorized · {groupedStlFiles.unlabeled.length} of {model.stl_files.length}
                        </span>,
                        groupedStlFiles.unlabeled,
                        true,
                        groupedStlFiles.labeled.length === 0,
                      )}
                    </>
                  ) : (
                    groupAlphabetically([...model.stl_files].sort((a, b) => a.filename.localeCompare(b.filename))).map(([band, bandFiles]) =>
                      renderSection(
                        band,
                        <span className="text-xs font-medium text-gray-400 font-mono">{band}</span>,
                        bandFiles,
                        false,
                      )
                    )
                  )}
                </div>
              );
            })()}
          </div>

          )} {/* end !horizontal_parts_layout for STL files */}

          {/* Other Files (PDFs, TXTs, ZIPs, etc.) — right column only when NOT horizontal */}
          {!settings.horizontal_parts_layout && (model.other_files ?? []).length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5 mb-2">
                <FileBox size={14} />
                Other Files ({(model.other_files ?? []).length})
              </h3>
              <div className="space-y-1">
                {(model.other_files ?? []).map((fp) => {
                  const name = fp.split(/[\\/]/).pop() ?? fp;
                  return (
                    <a
                      key={fp}
                      href={api.documentUrl(fp)}
                      download={name}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 hover:border-gray-600 hover:bg-gray-800 text-xs text-gray-300 hover:text-gray-100 transition-colors"
                    >
                      <FileBox size={12} className="shrink-0 text-gray-500" />
                      <span className="truncate">{name}</span>
                    </a>
                  );
                })}
              </div>
            </div>
          )}

          {/* File location — right column only when NOT horizontal */}
          {!settings.horizontal_parts_layout && <div className="mt-auto">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5 mb-2">
              <Folder size={14} />
              Location
            </h3>
            <div className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
              <p className="text-xs text-gray-400 break-all font-mono leading-relaxed">
                {model.native_folder_path || model.folder_path}
              </p>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={copyPath}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                >
                  {copiedPath ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                  {copiedPath ? "Copied!" : "Copy path"}
                </button>
                <button
                  onClick={openFolder}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
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
      {settings.horizontal_parts_layout && !editing && model && (() => {
        const supFileIds = new Set(model.stl_files.filter((f) => f.sup_of_id != null).map((f) => f.id));
        const colCount = settings.part_categories_enabled ? 5 : 4;
        const renderHRow = (f: typeof model.stl_files[0], depth: 0 | 1) => {
          const isSup = depth === 1;
          const isBase = !isSup && !supFileIds.has(f.id);
          const pt = partTypes[f.id] ?? "";
          const pn = partNames[f.id] ?? "";
          const isSelected = selectedStlFileId === f.id;
          return (
            <tr
              key={f.id}
              data-file-row={f.id}
              onClick={() => { setSelectedStlFileId(f.id); setViewMode("3d"); }}
              className={`cursor-pointer transition-colors ${isSelected ? "bg-indigo-950/40" : "hover:bg-gray-800/40"}`}
            >
              <td className="px-3 py-1.5">
                <div className={`flex items-center gap-1 ${isSup ? "pl-4" : ""}`}>
                  {isSup && <span className="text-gray-600 shrink-0 select-none text-[10px]">↳</span>}
                  <input
                    value={pn}
                    placeholder={autoPartName(f.filename)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => setPartNames((prev) => ({ ...prev, [f.id]: e.target.value }))}
                    onBlur={(e) => { const v = e.target.value.trim(); if (v !== (f.part_name ?? "")) savePartName(f.id, v); }}
                    onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                    className="w-full bg-transparent border border-transparent hover:border-gray-700 focus:border-indigo-500 rounded px-1.5 py-0.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:bg-gray-800 transition-colors"
                  />
                </div>
              </td>
              <td className="px-3 py-1.5">
                <span className="text-gray-400 font-mono truncate" title={f.filename}>{f.filename}</span>
              </td>
              {settings.part_categories_enabled && (
                <td className="px-3 py-1.5">
                  <input
                    list="part-category-list-h"
                    value={pt}
                    placeholder="Category…"
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => { const v = e.target.value; setPartTypes((prev) => ({ ...prev, [f.id]: toPascalCase(v) + (v.endsWith(" ") ? " " : "") })); }}
                    onBlur={(e) => savePartType(f.id, e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                    className="w-full bg-gray-800 border border-gray-700 focus:border-indigo-500 rounded px-1.5 py-0.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none"
                  />
                </td>
              )}
              <td className="px-3 py-1.5 text-right">
                {f.size_bytes ? (
                  <a href={api.stlUrl(f.path)} download={f.filename} onClick={(e) => e.stopPropagation()} className="text-gray-600 hover:text-gray-400 tabular-nums transition-colors">
                    {(f.size_bytes / 1024 / 1024).toFixed(1)} MB
                  </a>
                ) : null}
              </td>
              <td className="px-3 py-1.5">
                <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                  {isSup ? (
                    <button title="Remove link" onClick={() => unlinkSup(f.id)} className="text-gray-600 hover:text-rose-400 transition-colors">
                      <Unlink2 size={14} />
                    </button>
                  ) : isBase ? (
                    <button title="Link a sup" onClick={() => setLinkingBaseId(linkingBaseId === f.id ? null : f.id)} className={`transition-colors ${linkingBaseId === f.id ? "text-indigo-400" : "text-gray-600 hover:text-indigo-400"}`}>
                      <Link2 size={14} />
                    </button>
                  ) : null}
                  {isBase && linkingBaseId === f.id && (
                    <select
                      autoFocus
                      defaultValue=""
                      className="bg-gray-700 text-xs text-gray-300 rounded px-1.5 py-0.5 border border-gray-600 focus:outline-none focus:border-indigo-500"
                      onChange={(e) => { if (e.target.value) { linkSup(f.id, parseInt(e.target.value)); setLinkingBaseId(null); } }}
                      onBlur={() => setLinkingBaseId(null)}
                    >
                      <option value="" disabled>Link sup…</option>
                      {model.stl_files
                        .filter((sf) => sf.id !== f.id)
                        .sort((a, b) => a.filename.localeCompare(b.filename))
                        .map((sf) => {
                          const alreadyHere = sf.sup_of_id === f.id;
                          const linkedElsewhere = sf.sup_of_id != null && !alreadyHere;
                          return (
                            <option key={sf.id} value={sf.id} disabled={alreadyHere}>
                              {sf.filename}{alreadyHere ? " ✓" : linkedElsewhere ? " (linked)" : ""}
                            </option>
                          );
                        })}
                    </select>
                  )}
                </div>
              </td>
            </tr>
          );
        };
        const toggleHTable = (key: string) => setHTableCollapsed((prev) => {
          const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n;
        });
        const renderHGroupHeader = (key: string, label: React.ReactNode, count: number) => {
          const isCollapsed = hTableCollapsed.has(key);
          return (
            <tr
              key={`hdr-${key}`}
              className="cursor-pointer select-none bg-gray-800/70 hover:bg-gray-800 border-b border-gray-700/60"
              onClick={() => toggleHTable(key)}
            >
              <td colSpan={colCount} className="px-3 py-1.5">
                <div className="flex items-center justify-between">
                  {label}
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-600 tabular-nums">{count}</span>
                    {isCollapsed ? <ChevronRight size={11} className="text-gray-600" /> : <ChevronDown size={11} className="text-gray-600" />}
                  </div>
                </div>
              </td>
            </tr>
          );
        };
        return (
          <div className="flex flex-col gap-5 mt-4">

            {/* STL Files — horizontal table */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                  <FileBox size={14} />
                  Files ({model.stl_files.length})
                </h3>
                <div className="flex gap-2">
                  <button onClick={downloadAllFiles} disabled={downloadingAll} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-500 disabled:opacity-40 text-xs text-gray-400 hover:text-gray-200 transition-colors">
                    <FolderDown size={12} />
                    {downloadingAll ? "Zipping…" : "Download all"}
                  </button>
                  <button onClick={() => setShowKitBuilder(true)} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-indigo-950 border border-gray-700 hover:border-indigo-600 text-xs text-gray-400 hover:text-indigo-300 transition-colors">
                    <Wrench size={12} />
                    Kit Builder
                  </button>
                </div>
              </div>
              {settings.part_categories_enabled && (
                <datalist id="part-category-list-h">
                  {PART_TYPE_SUGGESTIONS.map((s) => <option key={s} value={s} />)}
                </datalist>
              )}
              <div className="overflow-x-auto overflow-y-auto max-h-[520px] rounded-lg border border-gray-800">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 z-10">
                    <tr className="border-b border-gray-700 bg-gray-900">
                      <th className="px-3 py-2 text-left text-gray-500 font-medium w-52">Name</th>
                      <th className="px-3 py-2 text-left text-gray-500 font-medium">Filename</th>
                      {settings.part_categories_enabled && <th className="px-3 py-2 text-left text-gray-500 font-medium w-36">Category</th>}
                      <th className="px-3 py-2 text-right text-gray-500 font-medium w-20">Size</th>
                      <th className="px-3 py-2 w-14"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800/60">
                    {settings.part_categories_enabled ? (
                      <>
                        {groupedStlFiles.labeled.map(([cat, catFiles]) => (
                          <Fragment key={cat}>
                            {renderHGroupHeader(cat, <span className="text-xs font-medium text-gray-400">{toPascalCase(cat)}</span>, catFiles.length)}
                            {!hTableCollapsed.has(cat) && buildFileHierarchy(catFiles).map(({ file: f, depth }) => renderHRow(f, depth))}
                          </Fragment>
                        ))}
                        {groupedStlFiles.unlabeled.length > 0 && (() => {
                          const key = "__uncategorized__";
                          return (
                            <Fragment key={key}>
                              {renderHGroupHeader(key, <span className="text-xs font-medium text-gray-500">Uncategorized · {groupedStlFiles.unlabeled.length} of {model.stl_files.length}</span>, groupedStlFiles.unlabeled.length)}
                              {!hTableCollapsed.has(key) && buildFileHierarchy(groupedStlFiles.unlabeled).map(({ file: f, depth }) => renderHRow(f, depth))}
                            </Fragment>
                          );
                        })()}
                      </>
                    ) : (
                      buildFileHierarchy(model.stl_files).map(({ file: f, depth }) => renderHRow(f, depth))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        );
      })()}

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

      {lightboxOpen && (() => {
        const hasGallery = model.image_paths.length > 0;
        const lbImages = hasGallery
          ? model.image_paths.map((p) => api.fileUrl(p))
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
