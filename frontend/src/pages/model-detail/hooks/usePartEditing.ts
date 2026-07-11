// STL file part-editing state + handlers for ModelDetail: per-file part types
// and names, the collapse state of the list sections, and sup-file linking.
// Extracted from ModelDetail.tsx (STUDIO-63 P3) — behavior-preserving.
//
// Mutations go through the TanStack query cache via the shell's patchModel so
// the file list, viewer, and kit builder all reflect edits immediately.

import { useState, useEffect, Dispatch, SetStateAction } from "react";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { useToast } from "../../../context/ToastContext";
import { useAppSettings } from "../../../context/AppSettingsContext";
import { toPascalCase, buildAlphaBand } from "../utils";

type StlFilePatch = Partial<{ sup_of_id: number | null; part_type: string | null; part_name: string | null }>;

export interface UsePartEditing {
  partTypes: Record<number, string>;
  setPartTypes: Dispatch<SetStateAction<Record<number, string>>>;
  partNames: Record<number, string>;
  setPartNames: Dispatch<SetStateAction<Record<number, string>>>;
  filesCollapsed: Set<string>;
  setFilesCollapsed: Dispatch<SetStateAction<Set<string>>>;
  linkingBaseId: number | null;
  setLinkingBaseId: Dispatch<SetStateAction<number | null>>;
  savePartType: (fileId: number, value: string) => Promise<void>;
  savePartName: (fileId: number, value: string) => Promise<void>;
  linkSup: (baseId: number, supId: number) => Promise<void>;
  unlinkSup: (supId: number) => Promise<void>;
}

export function usePartEditing(
  model: ModelDetailType | null,
  patchModel: (updater: (prev: ModelDetailType) => ModelDetailType) => void,
  selectedStlFileId: number | null,
): UsePartEditing {
  const { toast } = useToast();
  const { settings } = useAppSettings();
  const [partTypes, setPartTypes] = useState<Record<number, string>>({});
  const [partNames, setPartNames] = useState<Record<number, string>>({});
  const [filesCollapsed, setFilesCollapsed] = useState<Set<string>>(new Set());
  const [linkingBaseId, setLinkingBaseId] = useState<number | null>(null);

  // Sync local part-type / part-name state from the loaded model.
  useEffect(() => {
    if (model) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStlFileId]);

  const patchStlFile = (fileId: number, patch: StlFilePatch) =>
    patchModel((prev) => ({
      ...prev,
      stl_files: prev.stl_files.map((f) => f.id === fileId ? { ...f, ...patch } : f),
    }));

  // A locked model blocks every edit this hook makes — one guard
  // here covers manual edits, bulk recategorize, and drag-to-categorize
  // alike, since they all funnel through these same functions. The backend
  // rejects too (defense in depth); this just avoids the round trip and
  // gives a specific reason instead of a generic "try again" toast.
  const blockedByLock = (): boolean => {
    if (!model?.locked) return false;
    toast("This model is locked — unlock it to make changes.", "error");
    return true;
  };

  const savePartType = async (fileId: number, value: string) => {
    if (blockedByLock()) return;
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
        patchModel((prev) => ({
          ...prev,
          stl_files: prev.stl_files.map((f) => f.id === fileId ? { ...f, part_type: pt || null } : f),
        }));
      }
      for (const paired of linkedNeedingUpdate) {
        setPartTypes((prevState) => ({ ...prevState, [paired.id]: pt }));
        await api.models.updateSTLFile(paired.id, { part_type: pt || null });
        patchModel((prev) => ({
          ...prev,
          stl_files: prev.stl_files.map((f) => f.id === paired.id ? { ...f, part_type: pt || null } : f),
        }));
      }
    } catch {
      setPartTypes((prevState) => ({ ...prevState, [fileId]: saved }));
      toast("Couldn't save category — try again.", "error");
    }
  };

  const savePartName = async (fileId: number, value: string) => {
    if (blockedByLock()) return;
    const trimmed = value.trim() || null;
    try {
      await api.models.updateSTLFile(fileId, { part_name: trimmed });
      patchStlFile(fileId, { part_name: trimmed });
    } catch {
      toast("Couldn't save name — try again.", "error");
    }
  };

  const linkSup = async (baseId: number, supId: number) => {
    if (blockedByLock()) return;
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
    if (blockedByLock()) return;
    try {
      await api.models.updateSTLFile(supId, { sup_of_id: null });
      patchStlFile(supId, { sup_of_id: null });
    } catch {
      toast("Couldn't unlink file — try again.", "error");
    }
  };

  return {
    partTypes,
    setPartTypes,
    partNames,
    setPartNames,
    filesCollapsed,
    setFilesCollapsed,
    linkingBaseId,
    setLinkingBaseId,
    savePartType,
    savePartName,
    linkSup,
    unlinkSup,
  };
}
