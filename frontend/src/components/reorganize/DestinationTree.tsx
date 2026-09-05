import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import type { ReorganizeEntry } from "../../api/client";
// Named ...Builder, not ...Tree, purely so the module name can't collide with
// this component's on a case-insensitive filesystem — which is the same class
// of problem the tree's own collision badge is about.
import { buildDestinationTree, type DestinationNode } from "./destinationTreeBuilder";
import { KIND_LABEL, blockerFlags, isResolvable } from "./entryFlags";

/** Children (or leaf rows) drawn under one node before a "show all" appears.
 *  Lazy expansion is what keeps a wide library cheap — a collapsed node costs
 *  one row — but a single folder holding thousands of models would still
 *  render them all at once the moment it opens. This bounds that case without
 *  pulling in a virtualisation dependency. */
const CHILD_LIMIT = 200;

interface Props {
  /** Already filtered by creator and tab — the same array the list renders,
   *  so the two views can't disagree about what is in the plan. */
  entries: ReorganizeEntry[];
  /** The page's single definition of "selectable"; the tree only intersects. */
  selectableIds: ReadonlySet<number>;
  selected: ReadonlySet<number>;
  onSelect: (ids: number[], select: boolean) => void;
  /** Manifest-wide, from the entries themselves — decides whether a node is
   *  counted in packages as well as models. */
  packageMode: boolean;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Destination tree (STUDIO-404): the proposed layout as folders rather than
 *  as a paginated list of paths, for judging the shape of the result. Auditing
 *  and resolving individual rows stays in the list view — a leaf here offers
 *  selection, not the override form. */
export default function DestinationTree({ entries, selectableIds, selected, onSelect, packageMode }: Props) {
  const roots = useMemo(
    () => buildDestinationTree(entries, selectableIds),
    [entries, selectableIds],
  );
  // Paths the user has explicitly flipped, XOR'd against the default (top
  // level open, everything below closed). Storing the flips rather than the
  // open set means expansion survives a rebuild when the tab or creator
  // filter changes which nodes exist — and needs no seeding effect.
  const [flipped, setFlipped] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState<Set<string>>(new Set());

  const toggleIn = (setter: typeof setFlipped) => (path: string) =>
    setter((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  const toggleOpen = toggleIn(setFlipped);
  const expandList = toggleIn(setShowAll);

  if (roots.length === 0) {
    return <div className="text-sm text-text-muted py-6 text-center">No destinations in this view.</div>;
  }

  return (
    <div className="space-y-0.5">
      {roots.map((node) => (
        <TreeRow
          key={node.path}
          node={node}
          open={flipped.has(node.path) !== (node.depth === 0)}
          isOpen={(n) => flipped.has(n.path) !== (n.depth === 0)}
          onToggleOpen={toggleOpen}
          expanded={showAll}
          onExpandList={expandList}
          selectableIds={selectableIds}
          selected={selected}
          onSelect={onSelect}
          packageMode={packageMode}
        />
      ))}
    </div>
  );
}

interface RowProps {
  node: DestinationNode;
  open: boolean;
  isOpen: (node: DestinationNode) => boolean;
  onToggleOpen: (path: string) => void;
  expanded: Set<string>;
  onExpandList: (path: string) => void;
  selectableIds: ReadonlySet<number>;
  selected: ReadonlySet<number>;
  onSelect: (ids: number[], select: boolean) => void;
  packageMode: boolean;
}

function TreeRow(props: RowProps) {
  const { node, open, isOpen, onToggleOpen, expanded, onExpandList, selected, onSelect, packageMode } = props;
  const hasContent = node.children.length > 0 || node.entries.length > 0;

  const selectedHere = node.selectableIds.filter((id) => selected.has(id)).length;
  const allSelected = selectedHere > 0 && selectedHere === node.selectableIds.length;
  // A half-selected branch has to look different from both an empty one and a
  // full one, or the checkbox lies in one direction or the other.
  const someSelected = selectedHere > 0 && !allSelected;

  const showingAll = expanded.has(node.path);
  const visibleChildren = showingAll ? node.children : node.children.slice(0, CHILD_LIMIT);
  const visibleEntries = showingAll ? node.entries : node.entries.slice(0, CHILD_LIMIT);
  const hiddenCount =
    node.children.length - visibleChildren.length + (node.entries.length - visibleEntries.length);

  const sharedComplete = node.sharedPackageIds.every((id) => selected.has(id));

  return (
    <div style={{ marginLeft: node.depth === 0 ? 0 : 14 }}>
      <div className="flex items-center gap-2 py-1 px-2 rounded hover:bg-panel-secondary/50">
        <button
          type="button"
          onClick={() => onToggleOpen(node.path)}
          disabled={!hasContent}
          aria-expanded={hasContent ? open : undefined}
          aria-label={`${open ? "Collapse" : "Expand"} ${node.label}`}
          className="shrink-0 text-text-secondary-alt hover:text-text-primary disabled:opacity-30"
        >
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>

        {/* No checkbox at all when nothing below can be selected — same gate
            the list uses per row, so a fully-blocked branch never offers an
            action that would do nothing. */}
        {node.selectableIds.length > 0 && (
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected;
            }}
            onChange={() => onSelect(node.selectableIds, !allSelected)}
            // The count is in the accessible name because this is the
            // page-scoped "select all" hazard (STUDIO-160) in a new shape:
            // a node can select models that are nowhere on screen, so how
            // many has to be said before it applies, not after.
            aria-label={`${allSelected ? "Deselect" : "Select"} ${plural(node.selectableIds.length, "eligible model")} under ${node.label}`}
            className="shrink-0"
          />
        )}

        <Folder size={13} className="shrink-0 text-indigo-400" />
        <span className="text-sm text-text-primary-alt font-mono truncate" title={node.path}>
          {node.label}
        </span>

        <span className="text-xs text-text-secondary-alt shrink-0 ml-auto flex items-center gap-2">
          <span>
            {packageMode ? `${plural(node.entryCount, "package")} · ` : ""}
            {plural(node.modelCount, "model")} · {plural(node.fileCount, "file")}
            {node.selectableIds.length > 0 ? ` · ${node.selectableIds.length} eligible` : ""}
          </span>
          {node.collisionCount > 0 && (
            <span
              className="px-1.5 py-0.5 rounded bg-rose-950 text-rose-300"
              title="Models below this folder collide with another destination."
            >
              {node.collisionCount} collision{node.collisionCount === 1 ? "" : "s"}
            </span>
          )}
          {node.blockedCount > 0 && (
            <span
              className="px-1.5 py-0.5 rounded bg-amber-950 text-amber-300"
              title="Models below this folder can't be applied yet. Switch to the list view to resolve them."
            >
              {node.blockedCount} blocked
            </span>
          )}
        </span>
      </div>

      {open && (
        <>
          {/* The envelope sits on the character folder, which is where the
              all-or-nothing rule actually applies — and reads the whole
              selection, not this view's slice of it. */}
          {node.sharedFileCount > 0 && (
            <div
              className={`ml-8 px-2 py-0.5 text-xs ${sharedComplete ? "text-emerald-400" : "text-amber-400"}`}
            >
              {plural(node.sharedFileCount, "shared character file")}{" "}
              {sharedComplete
                ? "will move with the complete character"
                : `will remain unless all ${node.sharedPackageIds.length} packages are selected`}
            </div>
          )}

          {visibleChildren.map((child) => (
            <TreeRow {...props} key={child.path} node={child} open={isOpen(child)} />
          ))}

          {visibleEntries.map((entry) => {
            const flags = blockerFlags(entry);
            const canSelect = props.selectableIds.has(entry.model_id);
            return (
              <div key={entry.model_id} className="flex items-center gap-2 py-0.5 px-2 ml-6">
                {canSelect ? (
                  <input
                    type="checkbox"
                    checked={selected.has(entry.model_id)}
                    onChange={() => onSelect([entry.model_id], !selected.has(entry.model_id))}
                    aria-label={`Select ${entry.model_name}`}
                    className="shrink-0"
                  />
                ) : (
                  <span className="w-3.5 shrink-0" />
                )}
                <span className="text-xs px-1.5 py-0.5 rounded bg-panel-secondary text-text-primary-alt2 shrink-0">
                  {KIND_LABEL[entry.kind]}
                </span>
                <span className="text-sm text-text-primary-alt truncate">{entry.model_name}</span>
                {flags.map((flag) => (
                  <span
                    key={flag.label}
                    title={flag.explanation}
                    className={`text-xs px-1.5 py-0.5 rounded shrink-0 ${
                      isResolvable(entry) ? "bg-amber-950 text-amber-300" : "bg-rose-950 text-rose-300"
                    }`}
                  >
                    {flag.label}
                  </span>
                ))}
              </div>
            );
          })}

          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={() => onExpandList(node.path)}
              className="ml-8 px-2 py-0.5 text-xs text-indigo-400 hover:text-indigo-300"
            >
              Show {hiddenCount} more under {node.label}
            </button>
          )}
        </>
      )}
    </div>
  );
}
