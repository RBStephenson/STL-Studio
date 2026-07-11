// Horizontal STL file table for ModelDetail (the opt-in horizontal_parts_layout):
// resizable columns, part-name + part-type editing, sup-file linking, checkbox
// selection for bulk download, and drag-and-drop category assignment.
// Extracted from ModelDetail.tsx (STUDIO-63 P2 PR-4) — behavior-preserving;
// markup moved verbatim.
//
// Column-resize state (hColWidths, hTableRef), collapse state
// (hTableCollapsed), and the download-selection checkboxes are exclusive to
// this table, so they live here as local state. Shared file-editing state
// (partTypes, partNames, sup-linking, selection) is owned by the page shell
// and passed in as props. Renders null unless the horizontal layout is
// active and the page is not in edit mode.

import { Fragment, useEffect, useRef, useState, Dispatch, SetStateAction } from "react";
import {
  DndContext, DragEndEvent, PointerSensor, useDraggable, useDroppable, useSensor, useSensors,
} from "@dnd-kit/core";
import {
  FileBox, Wand2, Loader2, FolderDown, Wrench, ChevronDown, ChevronRight,
  Unlink2, Link2, GripVertical,
} from "lucide-react";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { PartTypeCombo } from "../../../components/PartTypeCombo";
import { FileLinkCombo, FileLinkOption } from "../../../components/FileLinkCombo";
import { useAppSettings } from "../../../context/AppSettingsContext";
import type { ViewMode } from "../utils";
import { PART_TYPE_SUGGESTIONS, toPascalCase, autoPartName, buildFileHierarchy, naturalCompare } from "../utils";

type StlFiles = ModelDetailType["stl_files"];
type StlFile = StlFiles[number];

interface GroupedStlFiles {
  labeled: [string, StlFiles][];
  unlabeled: StlFiles;
}

// Droppable id for the "no category" group header — dropping a file here
// clears its category, mirroring the label shown for uncategorized files.
const UNCATEGORIZED_DROP_ID = "__uncategorized__";

function DraggableFileRow({
  f, isSup, isBase, pt, pn, isSelected, isChecked, partCategoriesEnabled, categoryOptions,
  onSelectFile, onToggleCheck, setPartNames, savePartName, setPartTypes, savePartType,
  linkingBaseId, setLinkingBaseId, linkSup, unlinkSup, allFiles,
}: {
  f: StlFile;
  isSup: boolean;
  isBase: boolean;
  pt: string;
  pn: string;
  isSelected: boolean;
  isChecked: boolean;
  partCategoriesEnabled: boolean;
  categoryOptions: string[];
  onSelectFile: () => void;
  onToggleCheck: () => void;
  setPartNames: Dispatch<SetStateAction<Record<number, string>>>;
  savePartName: (fileId: number, value: string) => void;
  setPartTypes: Dispatch<SetStateAction<Record<number, string>>>;
  savePartType: (fileId: number, value: string) => void;
  linkingBaseId: number | null;
  setLinkingBaseId: Dispatch<SetStateAction<number | null>>;
  linkSup: (baseId: number, supId: number) => void;
  unlinkSup: (supId: number) => void;
  allFiles: StlFiles;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: f.id });
  return (
    <tr
      ref={setNodeRef}
      data-file-row={f.id}
      onClick={onSelectFile}
      className={`cursor-pointer transition-colors ${isSelected ? "bg-indigo-950/40" : "hover:bg-panel-secondary/40"} ${isDragging ? "opacity-40" : ""}`}
    >
      <td className="px-2 py-1.5 text-center" onClick={(e) => e.stopPropagation()}>
        <input type="checkbox" checked={isChecked} onChange={onToggleCheck} className="accent-violet-500" />
      </td>
      <td className="px-3 py-1.5">
        <div className={`flex items-center gap-1 ${isSup ? "pl-4" : ""}`}>
          {isSup && <span className="text-text-muted shrink-0 select-none text-[10px]">↳</span>}
          {partCategoriesEnabled && (
            <button
              {...attributes}
              {...listeners}
              onClick={(e) => e.stopPropagation()}
              title="Drag onto a category to assign it"
              className="shrink-0 text-text-muted hover:text-text-primary-alt2 cursor-grab active:cursor-grabbing touch-none"
            >
              <GripVertical size={12} />
            </button>
          )}
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
      {partCategoriesEnabled && (
        <td className="px-3 py-1.5">
          <PartTypeCombo
            value={pt}
            options={categoryOptions}
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
            <FileLinkCombo
              placeholder="Link sup…"
              className="w-32 bg-panel-secondary text-xs text-text-primary-alt2 rounded px-1.5 py-0.5 border border-border-divider focus:outline-none focus:border-accent-start"
              options={allFiles
                .filter((sf) => sf.id !== f.id)
                .sort((a, b) => naturalCompare(a.part_name || a.filename, b.part_name || b.filename))
                .map((sf): FileLinkOption => {
                  const alreadyHere = sf.sup_of_id === f.id;
                  const linkedElsewhere = sf.sup_of_id != null && !alreadyHere;
                  return {
                    id: sf.id,
                    label: sf.part_name || sf.filename,
                    filename: sf.filename,
                    disabled: alreadyHere,
                    suffix: alreadyHere ? " ✓" : linkedElsewhere ? " (linked)" : "",
                  };
                })}
              onPick={(id) => { linkSup(f.id, id); setLinkingBaseId(null); }}
              onCancel={() => setLinkingBaseId(null)}
            />
          )}
        </div>
      </td>
    </tr>
  );
}

function DroppableGroupHeaderRow({ id, label, count, colCount, collapsed, onToggle }: {
  id: string;
  label: React.ReactNode;
  count: number;
  colCount: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <tr
      ref={setNodeRef}
      className={`cursor-pointer select-none bg-panel-secondary/70 hover:bg-panel-secondary border-b border-border/60 transition-colors ${
        isOver ? "ring-2 ring-inset ring-accent-start bg-accent-start/20" : ""
      }`}
      onClick={onToggle}
    >
      <td colSpan={colCount} className="px-3 py-1.5">
        <div className="flex items-center justify-between">
          {label}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-text-muted tabular-nums">{count}</span>
            {collapsed ? <ChevronRight size={11} className="text-text-muted" /> : <ChevronDown size={11} className="text-text-muted" />}
          </div>
        </div>
      </td>
    </tr>
  );
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
  downloadingSelected: boolean;
  downloadSelectedFiles: (fileIds: number[]) => void;
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
  downloadingSelected,
  downloadSelectedFiles,
  onOpenKitBuilder,
}: StlFilesTableProps) {
  const { settings } = useAppSettings();
  const [hTableCollapsed, setHTableCollapsed] = useState<Set<string>>(new Set());
  const [hColWidths, setHColWidths] = useState<number[] | null>(null);
  const hTableRef = useRef<HTMLTableElement>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  // Drop the download-selection when navigating to a different model — a
  // stale selection silently downloading the wrong model's files would be
  // a nasty surprise.
  useEffect(() => { setSelectedIds(new Set()); }, [model.id]);

  if (!settings.horizontal_parts_layout || editing) return null;

  const supFileIds = new Set(model.stl_files.filter((f) => f.sup_of_id != null).map((f) => f.id));
  // +1 for the checkbox column, which every column-count consumer below
  // (colgroup, group-header colSpan) must also account for.
  const colCount = (settings.part_categories_enabled ? 5 : 4) + 1;
  const sizeColIdx = settings.part_categories_enabled ? 4 : 3;

  const toggleChecked = (id: number) => setSelectedIds((prev) => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  const allChecked = model.stl_files.length > 0 && model.stl_files.every((f) => selectedIds.has(f.id));
  const toggleAllChecked = () =>
    setSelectedIds(allChecked ? new Set() : new Set(model.stl_files.map((f) => f.id)));

  const handleDragEnd = (e: DragEndEvent) => {
    const overId = e.over?.id;
    if (overId == null) return;
    const fileId = e.active.id as number;
    const category = overId === UNCATEGORIZED_DROP_ID ? "" : (overId as string);
    savePartType(fileId, category);
  };

  // Standard suggestions plus whatever categories this model already uses
  // (groupedStlFiles.labeled keys are the persisted, Pascal-cased part_type
  // values in use) — deduped and alphabetized. Shared by the per-row Category
  // combo and the bulk "Recategorize to…" dropdown, so neither ever offers a
  // narrower list than the other — a custom category typed into one row's
  // combo must be pickable from every other row's combo too, not just the
  // bulk action.
  const categoryOptions = [...new Set([
    ...PART_TYPE_SUGGESTIONS,
    ...groupedStlFiles.labeled.map(([cat]) => cat),
  ])].sort(naturalCompare);

  const recategorizeSelected = async (category: string) => {
    await Promise.all([...selectedIds].map((id) => savePartType(id, category)));
    setSelectedIds(new Set());
  };

  const renderRow = (f: StlFile, depth: 0 | 1) => {
    const isSup = depth === 1;
    const isBase = !isSup && !supFileIds.has(f.id);
    return (
      <DraggableFileRow
        key={f.id}
        f={f}
        isSup={isSup}
        isBase={isBase}
        pt={partTypes[f.id] ?? ""}
        pn={partNames[f.id] ?? ""}
        isSelected={selectedStlFileId === f.id}
        isChecked={selectedIds.has(f.id)}
        partCategoriesEnabled={settings.part_categories_enabled}
        categoryOptions={categoryOptions}
        onSelectFile={() => { setSelectedStlFileId(f.id); setViewMode("3d"); }}
        onToggleCheck={() => toggleChecked(f.id)}
        setPartNames={setPartNames}
        savePartName={savePartName}
        setPartTypes={setPartTypes}
        savePartType={savePartType}
        linkingBaseId={linkingBaseId}
        setLinkingBaseId={setLinkingBaseId}
        linkSup={linkSup}
        unlinkSup={unlinkSup}
        allFiles={model.stl_files}
      />
    );
  };
  const toggleHTable = (key: string) => setHTableCollapsed((prev) => {
    const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n;
  });
  const renderHGroupHeader = (key: string, label: React.ReactNode, count: number) => (
    <DroppableGroupHeaderRow
      key={`hdr-${key}`}
      id={key}
      label={label}
      count={count}
      colCount={colCount}
      collapsed={hTableCollapsed.has(key)}
      onToggle={() => toggleHTable(key)}
    />
  );
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
            {selectedIds.size > 0 && settings.part_categories_enabled && (
              <select
                defaultValue=""
                onChange={(e) => { if (e.target.value) { recategorizeSelected(e.target.value); e.target.value = ""; } }}
                className="bg-panel-secondary border border-border hover:border-border-divider rounded px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary-alt focus:outline-none focus:border-accent-start transition-colors"
              >
                <option value="" disabled>Recategorize to…</option>
                {categoryOptions.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
              </select>
            )}
            {selectedIds.size > 0 && (
              <button
                onClick={() => downloadSelectedFiles([...selectedIds])}
                disabled={downloadingSelected}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border hover:border-border-divider disabled:opacity-40 text-xs text-text-secondary hover:text-text-primary-alt transition-colors"
              >
                <FolderDown size={12} />
                {downloadingSelected ? "Zipping…" : `Download selected (${selectedIds.size})`}
              </button>
            )}
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
          <DndContext sensors={dndSensors} onDragEnd={handleDragEnd}>
          <table ref={hTableRef} className={`text-xs table-fixed${hColWidths ? '' : ' w-full'}`} style={tableStyle}>
            {hColWidths && (
            <colgroup>
              <col style={{ width: hColWidths[0] }} />
              <col style={{ width: hColWidths[1] }} />
              <col style={{ width: hColWidths[2] }} />
              {settings.part_categories_enabled && <col style={{ width: hColWidths[3] }} />}
              <col style={{ width: hColWidths[sizeColIdx] }} />
            </colgroup>
            )}
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-panel">
                <th className="px-2 py-2 w-8 relative select-none overflow-hidden">
                  <input type="checkbox" checked={allChecked} onChange={toggleAllChecked} className="accent-violet-500" title="Select all" />
                </th>
                <th className="px-3 py-2 text-left text-text-secondary-alt font-medium relative select-none overflow-hidden">Name{resizeHandle(1)}</th>
                <th className="px-3 py-2 text-left text-text-secondary-alt font-medium relative select-none overflow-hidden">Filename{resizeHandle(2)}</th>
                {settings.part_categories_enabled && <th className="px-3 py-2 text-left text-text-secondary-alt font-medium relative select-none overflow-hidden">Category{resizeHandle(3)}</th>}
                <th className="px-3 py-2 text-right text-text-secondary-alt font-medium relative select-none overflow-hidden">Size{resizeHandle(sizeColIdx)}</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {settings.part_categories_enabled ? (
                <>
                  {groupedStlFiles.labeled.map(([cat, catFiles]) => (
                    <Fragment key={cat}>
                      {renderHGroupHeader(cat, <span className="text-xs font-medium text-text-secondary">{toPascalCase(cat)}</span>, catFiles.length)}
                      {!hTableCollapsed.has(cat) && buildFileHierarchy(catFiles).map(({ file: f, depth }) => renderRow(f, depth))}
                    </Fragment>
                  ))}
                  {groupedStlFiles.unlabeled.length > 0 && (() => {
                    const key = UNCATEGORIZED_DROP_ID;
                    return (
                      <Fragment key={key}>
                        {renderHGroupHeader(key, <span className="text-xs font-medium text-text-secondary-alt">Uncategorized · {groupedStlFiles.unlabeled.length} of {model.stl_files.length}</span>, groupedStlFiles.unlabeled.length)}
                        {!hTableCollapsed.has(key) && buildFileHierarchy(groupedStlFiles.unlabeled).map(({ file: f, depth }) => renderRow(f, depth))}
                      </Fragment>
                    );
                  })()}
                </>
              ) : (
                buildFileHierarchy(model.stl_files).map(({ file: f, depth }) => renderRow(f, depth))
              )}
            </tbody>
          </table>
          </DndContext>
            );
          })()}
        </div>
      </div>

    </div>
  );
}
