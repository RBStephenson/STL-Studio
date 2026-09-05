import type { ReorganizeEntry } from "../../api/client";

// Builds the destination tree for STUDIO-404 from a reorganize manifest.
//
// Pure and React-free on purpose: selection semantics are the load-bearing part
// of this feature and they are far cheaper to pin down against a plain function
// than through rendered checkboxes.
//
// Paths arrive already canonical — the backend stores every `proposed_dir`
// NFC-normalized with `/` separators (`reorganize._canon`) — so this splits on
// "/" and does no normalization of its own. Grouping is case-SENSITIVE: two
// destinations differing only by case really are two folders in the plan, and
// the rolled-up collision count is what tells you they will fight on a
// case-insensitive filesystem.

/** Shown instead of a blank row for an entry whose template produced no
 *  destination at all. Rare, but a nameless node is worse than a named one. */
export const NO_DESTINATION_LABEL = "(no destination)";

export interface DestinationNode {
  /** Full destination path. Unique across the tree, and the key expansion
   *  state is remembered by — so opening a node survives a filter change. */
  path: string;
  /** What the row renders: one segment, or several joined by "/" where a
   *  single-child chain was collapsed. */
  label: string;
  depth: number;
  children: DestinationNode[];
  /** Entries whose `proposed_dir` is exactly this node, not a descendant's. */
  entries: ReorganizeEntry[];
  /** Character-envelope files landing here (package mode). The backend
   *  attaches the envelope to ONE owner entry per character group, so these
   *  accumulate without any de-duplication needed. */
  sharedFileCount: number;
  /** Every package that has to be selected before the envelope above moves.
   *  Checked against the page's whole selection, never the filtered subset —
   *  the rule is about the plan, not about what is on screen. */
  sharedPackageIds: number[];
  // Everything below is rolled up over the subtree, inclusive of this node.
  modelCount: number;
  entryCount: number;
  fileCount: number;
  blockedCount: number;
  collisionCount: number;
  /** Subtree entries the page says are selectable. This is what a node
   *  checkbox acts on — never the model count, which is bigger. */
  selectableIds: number[];
}

interface Draft {
  path: string;
  label: string;
  children: Map<string, Draft>;
  entries: ReorganizeEntry[];
  sharedFileCount: number;
  sharedPackageIds: Set<number>;
}

const draft = (path: string, label: string): Draft => ({
  path,
  label,
  children: new Map(),
  entries: [],
  sharedFileCount: 0,
  sharedPackageIds: new Set(),
});

/**
 * Group entries into a directory tree by their proposed destination.
 *
 * `selectableIds` is passed in rather than derived here so there is exactly one
 * definition of "selectable" on the page — the tree intersects with it, it does
 * not get a vote.
 */
export function buildDestinationTree(
  entries: readonly ReorganizeEntry[],
  selectableIds: ReadonlySet<number>,
): DestinationNode[] {
  const roots = new Map<string, Draft>();

  // Walks (creating as it goes) to the node for one destination directory.
  // Levels are keyed by full path, not by bare segment, so a relative
  // destination could never land in the same bucket as an absolute one.
  const nodeAt = (dir: string): Draft => {
    const segments = (dir || "").split("/").filter(Boolean);
    if (segments.length === 0) {
      let bucket = roots.get("");
      if (!bucket) {
        bucket = draft("", NO_DESTINATION_LABEL);
        roots.set("", bucket);
      }
      return bucket;
    }
    const absolute = dir.startsWith("/");
    let level = roots;
    let node = draft("", "");
    let prefix = "";
    segments.forEach((segment, i) => {
      const label = i === 0 && absolute ? `/${segment}` : segment;
      prefix = i === 0 ? label : `${prefix}/${segment}`;
      let child = level.get(prefix);
      if (!child) {
        child = draft(prefix, label);
        level.set(prefix, child);
      }
      node = child;
      level = child.children;
    });
    return node;
  };

  for (const entry of entries) {
    nodeAt(entry.proposed_dir).entries.push(entry);
    // The envelope belongs one level up, at the character folder — attaching it
    // to the package node would hide the very rule it exists to make visible.
    if (entry.shared_files.length > 0 && entry.character_proposed_dir) {
      const owner = nodeAt(entry.character_proposed_dir);
      owner.sharedFileCount += entry.shared_files.length;
      for (const id of entry.character_package_ids) owner.sharedPackageIds.add(id);
    }
  }

  return [...roots.values()]
    .map((root) => finalize(root, 0, selectableIds))
    .sort(byLabel);
}

const byLabel = (a: DestinationNode, b: DestinationNode) => a.label.localeCompare(b.label);

function finalize(
  node: Draft,
  depth: number,
  selectableIds: ReadonlySet<number>,
): DestinationNode {
  // Collapse a run of single-child directories into one row, the way a file
  // browser does — it turns the "C:/STL Library/Models" spine into a single
  // node so the tree opens on creator → character → title. A node that owns
  // entries or a shared-file envelope is never collapsed away: it has
  // something of its own to render.
  let current = node;
  let label = node.label;
  while (
    current.children.size === 1 &&
    current.entries.length === 0 &&
    current.sharedFileCount === 0
  ) {
    const [only] = [...current.children.values()];
    label = `${label}/${only.label}`;
    current = only;
  }

  const children = [...current.children.values()]
    .map((child) => finalize(child, depth + 1, selectableIds))
    .sort(byLabel);

  let modelCount = 0;
  let entryCount = current.entries.length;
  let fileCount = current.sharedFileCount;
  let blockedCount = 0;
  let collisionCount = 0;
  const selectable: number[] = [];

  for (const entry of current.entries) {
    // One package entry stands for several models, so the two counts diverge
    // in package mode and the caller labels them differently.
    modelCount += entry.model_ids.length || 1;
    fileCount += entry.files.length;
    if (!entry.eligible) blockedCount += 1;
    if (entry.collision) collisionCount += 1;
    if (selectableIds.has(entry.model_id)) selectable.push(entry.model_id);
  }
  for (const child of children) {
    modelCount += child.modelCount;
    entryCount += child.entryCount;
    fileCount += child.fileCount;
    blockedCount += child.blockedCount;
    collisionCount += child.collisionCount;
    selectable.push(...child.selectableIds);
  }

  return {
    path: current.path,
    label,
    depth,
    children,
    entries: [...current.entries].sort((a, b) => a.model_name.localeCompare(b.model_name)),
    sharedFileCount: current.sharedFileCount,
    sharedPackageIds: [...current.sharedPackageIds].sort((a, b) => a - b),
    modelCount,
    entryCount,
    fileCount,
    blockedCount,
    collisionCount,
    selectableIds: selectable,
  };
}
