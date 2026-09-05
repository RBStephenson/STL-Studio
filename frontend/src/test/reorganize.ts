import type { ReorganizeEntry, ReorganizeFileMove } from "../api/client";

// Shared reorganize fixtures (STUDIO-404). ReorganizePage, DestinationTree and
// the tree builder all need a full manifest entry, and three hand-maintained
// copies of a ~25-field object drift apart the moment a field is added —
// the same problem STUDIO-406 fixed in the source. Follows the mkSettings
// pattern in ./settings.ts.

/** One file move inside an entry. The path doubles as source and destination
 *  because nothing that consumes these fixtures cares where it lands. */
export const mkFileMove = (
  path: string,
  over: Partial<ReorganizeFileMove> = {},
): ReorganizeFileMove => ({
  stl_file_id: null,
  current_path: path,
  proposed_path: path,
  size_bytes: 1,
  mtime_ns: 0,
  content_hash: null,
  fingerprint_method: "stat",
  missing_file: false,
  kind: "stl",
  ...over,
});

/** Full manifest entry for test mocks — override only what the test cares
 *  about. Defaults describe a plain, eligible, non-package move. */
export const mkEntry = (over: Partial<ReorganizeEntry> = {}): ReorganizeEntry => ({
  model_id: 1,
  model_name: "Joker Bust",
  creator_id: 1,
  creator_name: "Abe3D",
  model_ids: [1],
  package_mode: false,
  package_name: null,
  ambiguous_package: false,
  character_source_dir: null,
  character_proposed_dir: null,
  character_package_ids: [],
  character_model_ids: [],
  shared_files: [],
  source_path: "/lib/Abe3D/Joker/Bust",
  files: [],
  kind: "move",
  proposed_dir: "/lib/Abe3D/Joker/Bust",
  eligible: true,
  pack_override_paths: [],
  collision: false,
  collision_kind: "none",
  collision_with: [],
  suggested_suffix: null,
  unclassifiable: false,
  missing_fields: [],
  over_length: false,
  reserved_name: false,
  overlaps_other: false,
  spans_multiple_dirs: false,
  source_directories: [],
  is_symlink: false,
  escapes_scan_root: false,
  missing_files_on_disk: false,
  locked: false,
  ...over,
});
