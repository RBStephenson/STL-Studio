// Horizontal STL file table for ModelDetail (the opt-in horizontal_parts_layout):
// resizable columns, part-name + part-type editing, and sup-file linking.
// Extracted from ModelDetail.tsx (STUDIO-63 P2 PR-4) — behavior-preserving;
// markup moved verbatim.
//
// Column-resize state (hColWidths, hTableRef) and collapse state
// (hTableCollapsed) are exclusive to this table, so they live here as local
// state. Shared file-editing state (partTypes, partNames, sup-linking,
// selection) is owned by the page shell and passed in as props. Renders null
// unless the horizontal layout is active and the page is not in edit mode.

import { Fragment, useRef, useState, Dispatch, SetStateAction } from "react";
import {
  FileBox, Wand2, Loader2, FolderDown, Wrench, ChevronDown, ChevronRight,
  Unlink2, Link2,
} from "lucide-react";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { PartTypeCombo } from "../../../components/PartTypeCombo";
import { useAppSettings } from "../../../context/AppSettingsContext";
import type { ViewMode } from "../utils";
import { PART_TYPE_SUGGESTIONS, toPascalCase, autoPartName, buildFileHierarchy } from "../utils";

type StlFiles = ModelDetailType["stl_files"];

interface GroupedStlFiles {
  labeled: [string, StlFiles][];
  unlabeled: StlFiles;
}

interface StlFilesTableProps {
  model: ModelDetailType;
  editing: boolean;
  partTypes: Record<number, string>;
  setPartTypes: Dispatch<SetStateAction<Record<number, string>>>;
  savePartType: (fileId: number, value: string) => void;
  partNames: Record<number, string>;
  setPartNames: Dispatch<SetStateAction<Record<number, string>>>;
  savePartName: (fileId: number, value: string) => void;
  selectedStlFileId: number | null;
  setSelectedStlFileId: (id: number | null) => void;
  setViewMode: (mode: ViewMode) => void;
  linkingBaseId: number | null;
  setLinkingBaseId: Dispatch<SetStateAction<number | null>>;
  linkSup: (baseId: number, supId: number) => void;
  unlinkSup: (supId: number) => void;
  groupedStlFiles: GroupedStlFiles;
  aiOrganizing: boolean;
  runAiOrganize: () => void;
  downloadingAll: boolean;
  downloadAllFiles: () => void;
  onOpenKitBuilder: () => void;
}

export default function StlFilesTable({
  model,
  editing,
  partTypes,
  setPartTypes,
  savePartType,
  partNames,
  setPartNames,
  savePartName,
  selectedStlFileId,
  setSelectedStlFileId,
  setViewMode,
  linkingBaseId,
  setLinkingBaseId,
  linkSup,
  unlinkSup,
  groupedStlFiles,
  aiOrganizing,
  runAiOrganize,
  downloadingAll,
  downloadAllFiles,
  onOpenKitBuilder,
}: StlFilesTableProps) {
  const { settings } = useAppSettings();
  const [hTableCollapsed, setHTableCollapsed] = useState<Set<string>>(new Set());
  const [hColWidths, setHColWidths] = useState<number[] | null>(null);
  const hTableRef = useRef<HTMLTableElement>(null);

  if (!settings.horizontal_parts_layout || editing) return null;

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
        className={`cursor-pointer transition-colors ${isSelected ? "bg-indigo-950/40" : "hover:bg-panel-secondary/40"}`}
      >
        <td className="px-3 py-1.5">
          <div className={`flex items-center gap-1 ${isSup ? "pl-4" : ""}`}>
            {isSup && <span className="text-text-muted shrink-0 select-none text-[10px]">↳</span>}
            <input
              value={pn}
              placeholder={autoPartName(f.filename)}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setPartNames((prev) => ({ ...prev, [f.id]: e.target.value }))}
              onBlur={(e) => { const v = e.target.value.trim(); if (v !== (f.part_name ?? "")) savePartName(f.id, v); }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              className="w-full bg-transparent border border-transparent hover:border-border focus:border-accent-start rounded px-1.5 py-0.5 text-xs text-text-primary-alt2 placeholder-gray-600 focus:outline-none focus:bg-panel-secondary transition-colors"
            />
          </div>
        </td>
        <td className="px-3 py-1.5">
          <span className="text-text-secondary font-mono truncate" title={f.filename}>{f.filename}</span>
        </td>
        {settings.part_categories_enabled && (
          <td className="px-3 py-1.5">
            <PartTypeCombo
              value={pt}
              options={PART_TYPE_SUGGESTIONS}
              placeholder="Category…"
              onChange={(v) => setPartTypes((prev) => ({ ...prev, [f.id]: v }))}
              onCommit={(v) => savePartType(f.id, v)}
              className="w-full bg-panel-secondary border border-border focus:border-accent-start rounded px-1.5 py-0.5 text-xs text-text-primary-alt2 placeholder-gray-600 focus:outline-none"
            />
          </td>
        )}
        <td className="px-3 py-1.5 text-right">
          {f.size_bytes ? (
            <a href={api.stlUrl(f.path)} download={f.filename} onClick={(e) => e.stopPropagation()} className="text-text-muted hover:text-text-secondary tabular-nums transition-colors">
              {(f.size_bytes / 1024 / 1024).toFixed(1)} MB
            </a>
          ) : null}
        </td>
        <td className="px-3 py-1.5">
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            {isSup ? (
              <button title="Remove link" onClick={() => unlinkSup(f.id)} className="text-text-muted hover:text-rose-400 transition-colors">
                <Unlink2 size={14} />
              </button>
            ) : isBase ? (
              <button title="Link a sup" onClick={() => setLinkingBaseId(linkingBaseId === f.id ? null : f.id)} className={`transition-colors ${linkingBaseId === f.id ? "text-indigo-400" : "text-text-muted hover:text-indigo-400"}`}>
                <Link2 size={14} />
              </button>
            ) : null}
            {isBase && linkingBaseId === f.id && (
              <select
                autoFocus
                defaultValue=""
                className="bg-panel-secondary text-xs text-text-primary-alt2 rounded px-1.5 py-0.5 border border-border-divider focus:outline-none focus:border-accent-start"
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
        className="cursor-pointer select-none bg-panel-secondary/70 hover:bg-panel-secondary border-b border-border/60"
        onClick={() => toggleHTable(key)}
      >
        <td colSpan={colCount} className="px-3 py-1.5">
          <div className="flex items-center justify-between">
            {label}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-text-muted tabular-nums">{count}</span>
              {isCollapsed ? <ChevronRight size={11} className="text-text-muted" /> : <ChevronDown size={11} className="text-text-muted" />}
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
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-1.5">
            <FileBox size={14} />
            Files ({model.stl_files.length})
          </h3>
          <div className="flex gap-2">
            {settings.ai_organize_enabled && (
              <button onClick={runAiOrganize} disabled={aiOrganizing} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-violet-950 border border-border hover:border-violet-600 disabled:opacity-40 text-xs text-text-secondary hover:text-violet-300 transition-colors">
                {aiOrganizing
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Wand2 size={12} />}
                {aiOrganizing ? "Organizing…" : "AI Organize"}
              </button>
            )}
            <button onClick={downloadAllFiles} disabled={downloadingAll} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border hover:border-border-divider disabled:opacity-40 text-xs text-text-secondary hover:text-text-primary-alt transition-colors">
              <FolderDown size={12} />
              {downloadingAll ? "Zipping…" : "Download all"}
            </button>
            <button onClick={onOpenKitBuilder} className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-indigo-950 border border-border hover:border-indigo-600 text-xs text-text-secondary hover:text-indigo-300 transition-colors">
              <Wrench size={12} />
              Kit Builder
            </button>
          </div>
        </div>
        <div className="overflow-x-auto overflow-y-auto max-h-[520px] rounded-lg border border-border-subtle">
          {(() => {
            const startColResize = (colIdx: number, e: React.MouseEvent) => {
              e.preventDefault();
              // On first drag, snapshot current column widths from the DOM
              let snapshot = hColWidths;
              if (!snapshot && hTableRef.current) {
                const ths = Array.from(hTableRef.current.querySelectorAll('thead tr th'));
                snapshot = ths.map((th) => (th as HTMLElement).offsetWidth);
                setHColWidths(snapshot);
              }
              if (!snapshot) return;
              const startX = e.clientX;
              const startW = snapshot[colIdx];
              const onMove = (ev: MouseEvent) => {
                setHColWidths(prev => {
                  const base = prev ?? snapshot!;
                  const next = [...base];
                  next[colIdx] = Math.max(60, startW + ev.clientX - startX);
                  return next;
                });
              };
              const onUp = () => {
                window.removeEventListener('mousemove', onMove);
                window.removeEventListener('mouseup', onUp);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
              };
              document.body.style.cursor = 'col-resize';
              document.body.style.userSelect = 'none';
              window.addEventListener('mousemove', onMove);
              window.addEventListener('mouseup', onUp);
            };
            const resizeHandle = (colIdx: number) => (
              <div
                className="absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize group/rh flex items-stretch"
                onMouseDown={(e) => startColResize(colIdx, e)}
              >
                <div className="w-px mx-auto bg-panel-secondary group-hover/rh:bg-accent-start transition-colors" />
              </div>
            );
            const tableStyle = hColWidths
              ? { width: hColWidths.reduce((a, b) => a + b, 0), minWidth: hColWidths.reduce((a, b) => a + b, 0) }
              : undefined;
            return (
          <table ref={hTableRef} className={`text-xs table-fixed${hColWidths ? '' : ' w-full'}`} style={tableStyle}>
            {hColWidths && (
            <colgroup>
              <col style={{ width: hColWidths[0] }} />
              <col style={{ width: hColWidths[1] }} />
              {settings.part_categories_enabled && <col style={{ width: hColWidths[2] }} />}
              <col style={{ width: hColWidths[3] }} />
              <col style={{ width: hColWidths[4] }} />
            </colgroup>
            )}
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-panel">
                <th className="px-3 py-2 text-left text-text-secondary-alt font-medium relative select-none overflow-hidden">Name{resizeHandle(0)}</th>
                <th className="px-3 py-2 text-left text-text-secondary-alt font-medium relative select-none overflow-hidden">Filename{resizeHandle(1)}</th>
                {settings.part_categories_enabled && <th className="px-3 py-2 text-left text-text-secondary-alt font-medium relative select-none overflow-hidden">Category{resizeHandle(2)}</th>}
                <th className="px-3 py-2 text-right text-text-secondary-alt font-medium relative select-none overflow-hidden">Size{resizeHandle(3)}</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {settings.part_categories_enabled ? (
                <>
                  {groupedStlFiles.labeled.map(([cat, catFiles]) => (
                    <Fragment key={cat}>
                      {renderHGroupHeader(cat, <span className="text-xs font-medium text-text-secondary">{toPascalCase(cat)}</span>, catFiles.length)}
                      {!hTableCollapsed.has(cat) && buildFileHierarchy(catFiles).map(({ file: f, depth }) => renderHRow(f, depth))}
                    </Fragment>
                  ))}
                  {groupedStlFiles.unlabeled.length > 0 && (() => {
                    const key = "__uncategorized__";
                    return (
                      <Fragment key={key}>
                        {renderHGroupHeader(key, <span className="text-xs font-medium text-text-secondary-alt">Uncategorized · {groupedStlFiles.unlabeled.length} of {model.stl_files.length}</span>, groupedStlFiles.unlabeled.length)}
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
            );
          })()}
        </div>
      </div>

    </div>
  );
}
