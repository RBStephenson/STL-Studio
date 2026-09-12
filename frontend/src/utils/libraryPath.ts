// Build a display path under a library root using the root's OWN separator
// (STUDIO-452). The browser can't know what OS the backend runs on, but a
// library path arrives already built by pathlib on that host, so the stored
// path is the only honest source of truth available here.
//
// Display only. The backend builds the real destination itself; nothing joined
// here ever reaches a filesystem. Deliberately NOT used for reorganize's
// destination tree, which parses proposed_dir values the backend canonicalizes
// to forward slashes (reorganize._canon) and is self-consistent as a result.

const WINDOWS_SEPARATOR = "\\";
const POSIX_SEPARATOR = "/";
const TRAILING_SEPARATORS = /[\\/]+$/;

function separatorFor(root: string): string {
  return root.includes(WINDOWS_SEPARATOR) ? WINDOWS_SEPARATOR : POSIX_SEPARATOR;
}

export function joinLibraryPath(root: string, ...segments: string[]): string {
  const separator = separatorFor(root);
  const parts = segments.filter((segment) => segment.length > 0);
  const trimmedRoot = root.replace(TRAILING_SEPARATORS, "");
  // A root written as nothing but separators ("/" on POSIX) trims away to
  // nothing, but that separator *is* the root and has to survive the join.
  const base = trimmedRoot || (root.length > 0 ? separator : "");

  if (parts.length === 0) return base;
  if (!base) return parts.join(separator);
  return base.endsWith(separator)
    ? `${base}${parts.join(separator)}`
    : `${base}${separator}${parts.join(separator)}`;
}
