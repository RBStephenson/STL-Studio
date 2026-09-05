import type { ReorganizeEntry, ReorganizeMoveKind, ReorganizeCollisionKind } from "../../api/client";

// Lifted out of ReorganizePage verbatim (STUDIO-404) so the destination tree
// labels a blocked row with the SAME words the list does. The alternative was
// a second vocabulary invented inside the tree, which is the exact drift
// STUDIO-406 spent a ticket deleting.

export const KIND_LABEL: Record<ReorganizeMoveKind, string> = {
  move: "move",
  rename: "rename",
  case_rename: "case rename",
  in_place: "in place",
  merge: "merge",
};

export const COLLISION_EXPLANATIONS: Record<ReorganizeCollisionKind, string> = {
  none: "",
  exact: "Another model already resolves to this exact destination path.",
  case_only: "Another model's destination path differs only by letter case — that collides on case-insensitive filesystems.",
  same_destination: "Another model resolves to this same destination. This does not mean their files are duplicates.",
};

export interface BlockerFlag {
  label: string;
  explanation: string;
}

/** Blocker/flag chips for a single entry, each with a plain-English
 *  explanation (STUDIO-162) — previously chips were bare codes like
 *  "locked" or "over-length" with no way to know why or what to do. */
export function blockerFlags(e: ReorganizeEntry): BlockerFlag[] {
  const flags: BlockerFlag[] = [];
  if (e.ambiguous_package) {
    flags.push({
      label: "package boundary",
      explanation: "The model's character does not match a physical ancestor folder, so Reorganize cannot safely determine the release package boundary.",
    });
  }
  if (e.collision) {
    flags.push({
      label: `collision: ${e.collision_kind}`,
      explanation: `${COLLISION_EXPLANATIONS[e.collision_kind]}${
        e.collision_with.length ? ` Conflicts with ${e.collision_with.length} other model(s).` : ""
      }`,
    });
  }
  if (e.unclassifiable) {
    flags.push({
      label: "unclassifiable",
      explanation: e.missing_fields.length
        ? `Missing a value for: ${e.missing_fields.join(", ")}. Fill it in below to resolve.`
        : "The destination template needs a value this model doesn't have. Fill it in below to resolve.",
    });
  }
  if (e.over_length) {
    flags.push({ label: "over-length", explanation: "The proposed path is too long for the filesystem. Shorten a field below (e.g. use a suffix) to resolve." });
  }
  if (e.reserved_name) {
    flags.push({ label: "reserved name", explanation: "The proposed name is reserved by the operating system (e.g. CON, NUL). Adjust a field below to resolve." });
  }
  if (e.overlaps_other) {
    flags.push({ label: "overlap", explanation: "This model's files overlap with another model's files on disk. Needs a rescan or manual disk fix — not resolvable here." });
  }
  if (e.spans_multiple_dirs) {
    const directories = e.source_directories.length
      ? ` Source directories: ${e.source_directories.join("; ")}.`
      : "";
    flags.push({
      label: "multi-dir",
      explanation: `This model's STL files are spread across multiple directories, so Reorganize can't safely move it as one unit.${directories} Needs a manual disk fix.`,
    });
  }
  if (e.is_symlink) {
    flags.push({ label: "symlink", explanation: "One or more files are symlinks — Reorganize skips symlinked files to avoid moving something it doesn't actually own." });
  }
  if (e.escapes_scan_root) {
    flags.push({ label: "escapes root", explanation: "The proposed destination would land outside the scan root, which Reorganize refuses to do for safety." });
  }
  if (e.missing_files_on_disk) {
    flags.push({ label: "missing files", explanation: "One or more of this model's files are missing on disk. Rescan the library to refresh what's tracked." });
  }
  if (e.locked) {
    flags.push({ label: "locked", explanation: "This model is locked and won't be touched by Reorganize until it's unlocked." });
  }
  return flags;
}

/** Which blockers a user can resolve here (the rest need a rescan / disk fix).
 *  Drives both the amber-vs-rose row coloring (STUDIO-161) and, since
 *  STUDIO-400, whether a BLOCKED row offers the override form — eligible rows
 *  always offer it, so this only decides the blocked case. */
export function isResolvable(e: ReorganizeEntry): boolean {
  return e.unclassifiable || e.collision || e.over_length || e.reserved_name;
}
