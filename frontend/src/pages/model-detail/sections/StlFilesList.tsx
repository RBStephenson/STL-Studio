// Vertical hierarchical STL file list for ModelDetail (the default,
// non-horizontal layout): collapsible category/alpha sections, inline part-type
// editing, and sup-file linking. Extracted from ModelDetail.tsx
// (STUDIO-63 P2 PR-3) — behavior-preserving; markup moved verbatim.
//
// File-editing state (partTypes, collapse sets, sup-linking) is owned by the
// page shell and passed in, because it is shared with the horizontal-table
// layout and the STL viewer selection. Renders null in horizontal layout.

import { Dispatch, SetStateAction } from "react";
import {
  FileBox, Wand2, Loader2, FolderDown, Wrench, ChevronDown, ChevronRight,
  Unlink2, Link2, X,
} from "lucide-react";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { PartTypeCombo } from "../../../components/PartTypeCombo";
import { useAppSettings } from "../../../context/AppSettingsContext";
import type { ViewMode } from "../utils";
import {
  PART_TYPE_SUGGESTIONS, toPascalCase, buildFileHierarchy, groupAlphabetically,
} from "../utils";

type StlFiles = ModelDetailType["stl_files"];

interface GroupedStlFiles {
  labeled: [string, StlFiles][];
  unlabeled: StlFiles;
}

interface StlFilesListProps {
  model: ModelDetailType;
  partTypes: Record<number, string>;
  setPartTypes: Dispatch<SetStateAction<Record<number, string>>>;
  savePartType: (fileId: number, value: string) => void;
  selectedStlFileId: number | null;
  setSelectedStlFileId: (id: number | null) => void;
  setViewMode: (mode: ViewMode) => void;
  linkingBaseId: number | null;
  setLinkingBaseId: Dispatch<SetStateAction<number | null>>;
  linkSup: (baseId: number, supId: number) => void;
  unlinkSup: (supId: number) => void;
  filesCollapsed: Set<string>;
  setFilesCollapsed: Dispatch<SetStateAction<Set<string>>>;
  groupedStlFiles: GroupedStlFiles;
  aiOrganizing: boolean;
  runAiOrganize: () => void;
  downloadingAll: boolean;
  downloadAllFiles: () => void;
  onOpenKitBuilder: () => void;
}

export default function StlFilesList({
  model,
  partTypes,
  setPartTypes,
  savePartType,
  selectedStlFileId,
  setSelectedStlFileId,
  setViewMode,
  linkingBaseId,
  setLinkingBaseId,
  linkSup,
  unlinkSup,
  filesCollapsed,
  setFilesCollapsed,
  groupedStlFiles,
  aiOrganizing,
  runAiOrganize,
  downloadingAll,
  downloadAllFiles,
  onOpenKitBuilder,
}: StlFilesListProps) {
  const { settings } = useAppSettings();

  if (settings.horizontal_parts_layout) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          <FileBox size={14} />
          Files ({model.stl_files.length})
        </h3>
        {model.stl_files.length > 0 && (
          <div className="flex gap-2">
            {settings.ai_organize_enabled && (
              <button
                onClick={runAiOrganize}
                disabled={aiOrganizing}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-violet-950 border border-gray-700 hover:border-violet-600 disabled:opacity-40 text-xs text-gray-400 hover:text-violet-300 transition-colors"
              >
                {aiOrganizing
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Wand2 size={12} />}
                {aiOrganizing ? "Organizing…" : "AI Organize"}
              </button>
            )}
            <button
              onClick={downloadAllFiles}
              disabled={downloadingAll}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-500 disabled:opacity-40 text-xs text-gray-400 hover:text-gray-200 transition-colors"
            >
              <FolderDown size={12} />
              {downloadingAll ? "Zipping…" : "Download all"}
            </button>
            <button
              onClick={onOpenKitBuilder}
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
                  <PartTypeCombo
                    value={pt}
                    options={PART_TYPE_SUGGESTIONS}
                    placeholder="Category…"
                    onChange={(v) => setPartTypes((prev) => ({ ...prev, [f.id]: toPascalCase(v) + (v.endsWith(" ") ? " " : "") }))}
                    onCommit={(v) => savePartType(f.id, v)}
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
  );
}
