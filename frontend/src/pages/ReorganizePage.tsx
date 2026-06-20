import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ReorganizeEntry, ReorganizePreview, ReorganizeMoveKind } from "../api/client";
import ReorganizeStatsBar from "../components/reorganize/ReorganizeStatsBar";

const DEFAULT_TEMPLATE = "{creator}/{character}/{title}";
const DEBOUNCE_MS = 500;

type FilterTab = "all" | "moves" | "collisions" | "unclassifiable" | "blocked" | "in_place";

const FILTERS: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "moves", label: "Moves" },
  { key: "collisions", label: "Collisions" },
  { key: "unclassifiable", label: "Unclassifiable" },
  { key: "blocked", label: "Blocked" },
  { key: "in_place", label: "Already In Place" },
];

const KIND_LABEL: Record<ReorganizeMoveKind, string> = {
  move: "move",
  rename: "rename",
  case_rename: "case rename",
  in_place: "in place",
  merge: "merge",
};

function matchesFilter(e: ReorganizeEntry, tab: FilterTab): boolean {
  switch (tab) {
    case "all": return true;
    case "moves": return ["move", "rename", "case_rename"].includes(e.kind);
    case "collisions": return e.collision;
    case "unclassifiable": return e.unclassifiable;
    case "blocked": return !e.eligible;
    case "in_place": return e.kind === "in_place";
  }
}

/** Blocker/flag chips for a single entry — empty when the entry is clean. */
function blockerChips(e: ReorganizeEntry): string[] {
  const chips: string[] = [];
  if (e.collision) chips.push(`collision: ${e.collision_kind}`);
  if (e.unclassifiable) chips.push("unclassifiable");
  if (e.over_length) chips.push("over-length");
  if (e.reserved_name) chips.push("reserved name");
  if (e.overlaps_other) chips.push("overlap");
  if (e.spans_multiple_dirs) chips.push("multi-dir");
  if (e.is_symlink) chips.push("symlink");
  if (e.escapes_scan_root) chips.push("escapes root");
  if (e.missing_files_on_disk) chips.push("missing files");
  return chips;
}

export default function ReorganizePage() {
  const [template, setTemplate] = useState(DEFAULT_TEMPLATE);
  const [preview, setPreview] = useState<ReorganizePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<FilterTab>("all");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = await api.reorganize.preview(template);
        if (!cancelled) { setPreview(data); setError(null); }
      } catch (e) {
        if (!cancelled) {
          // A malformed template returns 400 with a helpful detail message.
          setError(e instanceof ApiError ? e.message : "Failed to load preview");
          if (e instanceof ApiError && e.status === 400) setPreview(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(t); };
  }, [template]);

  const visible = useMemo(
    () => preview?.entries.filter((e) => matchesFilter(e, tab)) ?? [],
    [preview, tab],
  );

  const toggle = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Reorganize Library (preview)</h1>
        <p className="text-sm text-gray-500 mt-1">
          Preview only — no files are moved. Review the proposed layout before a
          future release adds the apply step.
        </p>
      </div>

      {/* Template editor */}
      <div className="space-y-2">
        <label className="block text-sm text-gray-300">Destination template</label>
        <input
          type="text"
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 font-mono focus:outline-none focus:border-indigo-500"
          aria-label="Destination template"
        />
        <div className="text-xs text-gray-500">
          Tokens: <code className="text-indigo-400">{"{creator}"}</code>{" "}
          <code className="text-indigo-400">{"{character}"}</code>{" "}
          <code className="text-indigo-400">{"{title}"}</code> — separate levels with <code>/</code>.
        </div>
        {error && <div className="text-sm text-rose-400">{error}</div>}
      </div>

      {preview && (
        <>
          <ReorganizeStatsBar stats={preview.stats} />

          {/* Filter tabs */}
          <div className="flex gap-1 flex-wrap border-b border-gray-800">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setTab(f.key)}
                className={`px-3 py-1.5 text-sm rounded-t ${
                  tab === f.key
                    ? "bg-gray-800 text-gray-100 border-b-2 border-indigo-500"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Manifest table */}
          <div className="space-y-1">
            {visible.length === 0 && (
              <div className="text-sm text-gray-600 py-6 text-center">No models in this view.</div>
            )}
            {visible.map((e) => {
              const chips = blockerChips(e);
              const isOpen = expanded.has(e.model_id);
              return (
                <div
                  key={e.model_id}
                  className={`rounded border ${e.eligible ? "border-gray-800" : "border-orange-900/60 bg-orange-950/20"}`}
                >
                  <button
                    onClick={() => toggle(e.model_id)}
                    className="w-full flex items-center gap-3 px-3 py-2 text-left"
                  >
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-300 shrink-0">
                      {KIND_LABEL[e.kind]}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm text-gray-200 truncate">{e.model_name}</span>
                      <span className="block text-xs text-gray-500 truncate font-mono">
                        → {e.proposed_dir}
                      </span>
                    </span>
                    {chips.map((c) => (
                      <span key={c} className="text-xs px-2 py-0.5 rounded bg-rose-950 text-rose-300 shrink-0">
                        {c}
                      </span>
                    ))}
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-2 space-y-1 border-t border-gray-800 pt-2">
                      {e.files.map((f) => (
                        <div key={f.stl_file_id} className="text-xs font-mono text-gray-500">
                          <span className="text-gray-600">{f.current_path}</span>
                          <span className="text-gray-700"> → </span>
                          <span className="text-gray-400">{f.proposed_path}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {loading && !preview && <div className="text-sm text-gray-500">Loading preview…</div>}

      {/* Apply — wired in Phase 2 (#324) against manifest_id */}
      <div className="pt-2">
        <button
          type="button"
          disabled
          title="Coming in a future release"
          className="px-4 py-2 rounded bg-gray-800 text-gray-600 text-sm cursor-not-allowed"
        >
          Apply
        </button>
      </div>
    </div>
  );
}
