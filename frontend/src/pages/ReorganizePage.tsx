import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import type {
  ReorganizeEntry,
  ReorganizePreview,
  ReorganizeMoveKind,
  ReorganizeOverride,
  ReorganizeApplyResult,
} from "../api/client";
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
  if (e.locked) chips.push("locked");
  return chips;
}

/** Which blockers a user can resolve here (the rest need a rescan / disk fix). */
function isResolvable(e: ReorganizeEntry): boolean {
  return e.unclassifiable || e.collision || e.over_length || e.reserved_name;
}

export default function ReorganizePage() {
  const { settings } = useAppSettings();
  const [template, setTemplate] = useState(DEFAULT_TEMPLATE);
  // Seed the field from the saved library setting once it's loaded (async),
  // but only until the user starts typing their own one-off template.
  const [templateTouched, setTemplateTouched] = useState(false);
  useEffect(() => {
    if (!templateTouched && settings.reorganize_template) {
      setTemplate(settings.reorganize_template);
    }
  }, [settings.reorganize_template, templateTouched]);
  const [overrides, setOverrides] = useState<Record<number, ReorganizeOverride>>({});
  const [preview, setPreview] = useState<ReorganizePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<FilterTab>("all");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [applyMsg, setApplyMsg] = useState<string | null>(null);
  const [applyErr, setApplyErr] = useState<string | null>(null);
  const [lastApply, setLastApply] = useState<ReorganizeApplyResult | null>(null);

  const hasOverrides = Object.keys(overrides).length > 0;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = hasOverrides
          ? await api.reorganize.previewWithOverrides({ template, overrides })
          : await api.reorganize.preview(template);
        if (!cancelled) { setPreview(data); setError(null); }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Failed to load preview");
          if (e instanceof ApiError && e.status === 400) setPreview(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(t); };
  }, [template, overrides, hasOverrides]);

  const visible = useMemo(
    () => preview?.entries.filter((e) => matchesFilter(e, tab)) ?? [],
    [preview, tab],
  );

  const eligibleIds = useMemo(
    () => new Set((preview?.entries ?? []).filter((e) => e.eligible && e.kind !== "in_place").map((e) => e.model_id)),
    [preview],
  );

  // Drop selections that are no longer eligible after a re-preview.
  useEffect(() => {
    setSelected((prev) => new Set([...prev].filter((id) => eligibleIds.has(id))));
  }, [eligibleIds]);

  const toggle = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleSelect = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const setOverride = (id: number, patch: Partial<ReorganizeOverride>) =>
    setOverrides((prev) => {
      const merged = { ...prev[id], ...patch };
      // Drop empty fields; remove the entry entirely if nothing's left.
      const cleaned: ReorganizeOverride = {};
      for (const [k, v] of Object.entries(merged)) {
        if (v && String(v).trim()) (cleaned as Record<string, string>)[k] = v as string;
      }
      const next = { ...prev };
      if (Object.keys(cleaned).length) next[id] = cleaned;
      else delete next[id];
      return next;
    });

  const runApply = async () => {
    if (!preview || selected.size === 0) return;
    setBusy(true); setApplyMsg(null); setApplyErr(null);
    try {
      const res = await api.reorganize.apply(preview.manifest_id, [...selected]);
      setLastApply(res);
      setApplyMsg(`Moved ${res.moved_files} file(s) across ${res.moved_models} model(s).`);
      setSelected(new Set());
      // Files are now in their new homes — re-preview reflects reality.
      const fresh = await api.reorganize.preview(template);
      setPreview(fresh); setOverrides({});
    } catch (e) {
      setApplyErr(e instanceof ApiError ? e.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  };

  const runUndo = async () => {
    if (!lastApply) return;
    setBusy(true); setApplyMsg(null); setApplyErr(null);
    try {
      const res = await api.reorganize.undo(lastApply.manifest_id);
      const skip = res.skipped.length ? `, ${res.skipped.length} skipped` : "";
      setApplyMsg(`Reversed ${res.reversed_files} file(s)${skip}.`);
      setLastApply(null);
      const fresh = await api.reorganize.preview(template);
      setPreview(fresh);
    } catch (e) {
      setApplyErr(e instanceof ApiError ? e.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Reorganize Library</h1>
        <p className="text-sm text-text-secondary-alt mt-1">
          Preview the proposed layout, resolve any flagged rows, then apply. Apply
          moves files on disk and requires a writable standalone deployment.
        </p>
      </div>

      {/* Template editor */}
      <div className="space-y-2">
        <label className="block text-sm text-text-primary-alt2">Destination template</label>
        <input
          type="text"
          value={template}
          onChange={(e) => { setTemplate(e.target.value); setTemplateTouched(true); }}
          className="w-full bg-panel border border-border rounded px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:border-accent-start"
          aria-label="Destination template"
        />
        <div className="text-xs text-text-secondary-alt">
          Tokens: <code className="text-indigo-400">{"{creator}"}</code>{" "}
          <code className="text-indigo-400">{"{character}"}</code>{" "}
          <code className="text-indigo-400">{"{scale}"}</code>{" "}
          <code className="text-indigo-400">{"{title}"}</code> — separate levels with <code>/</code>.
        </div>
        {error && <div className="text-sm text-rose-400">{error}</div>}
      </div>

      {preview && (
        <>
          <ReorganizeStatsBar stats={preview.stats} />

          {/* Filter tabs */}
          <div className="flex gap-1 flex-wrap border-b border-border-subtle">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setTab(f.key)}
                className={`px-3 py-1.5 text-sm rounded-t ${
                  tab === f.key
                    ? "bg-panel-secondary text-text-primary border-b-2 border-accent-start"
                    : "text-text-secondary-alt hover:text-text-primary-alt2"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Manifest table */}
          <div className="space-y-1">
            {visible.length === 0 && (
              <div className="text-sm text-text-muted py-6 text-center">No models in this view.</div>
            )}
            {visible.map((e) => {
              const chips = blockerChips(e);
              const isOpen = expanded.has(e.model_id);
              const canSelect = eligibleIds.has(e.model_id);
              return (
                <div
                  key={e.model_id}
                  className={`rounded border ${e.eligible ? "border-border-subtle" : "border-orange-900/60 bg-orange-950/20"}`}
                >
                  <div className="w-full flex items-center gap-3 px-3 py-2">
                    {canSelect && (
                      <input
                        type="checkbox"
                        checked={selected.has(e.model_id)}
                        onChange={() => toggleSelect(e.model_id)}
                        aria-label={`Select ${e.model_name}`}
                        className="shrink-0"
                      />
                    )}
                    <button onClick={() => toggle(e.model_id)} className="flex items-center gap-3 text-left flex-1 min-w-0">
                      <span className="text-xs px-2 py-0.5 rounded bg-panel-secondary text-text-primary-alt2 shrink-0">
                        {KIND_LABEL[e.kind]}
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm text-text-primary-alt truncate">{e.model_name}</span>
                        <span className="block text-xs text-text-secondary-alt truncate font-mono">→ {e.proposed_dir}</span>
                      </span>
                    </button>
                    {chips.map((c) => (
                      <span key={c} className="text-xs px-2 py-0.5 rounded bg-rose-950 text-rose-300 shrink-0">
                        {c}
                      </span>
                    ))}
                  </div>
                  {isOpen && (
                    <div className="px-3 pb-2 space-y-2 border-t border-border-subtle pt-2">
                      {e.files.map((f) => (
                        <div key={f.current_path} className="text-xs font-mono text-text-secondary-alt">
                          <span className="text-text-muted">{f.current_path}</span>
                          <span className="text-text-muted-alt"> → </span>
                          <span className="text-text-secondary">{f.proposed_path}</span>
                        </div>
                      ))}
                      {!e.eligible && isResolvable(e) && (
                        <div className="pt-2 border-t border-border-subtle/60">
                          <div className="text-xs text-text-secondary mb-1">Resolve</div>
                          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                            {(["creator", "character", "scale", "title", "suffix"] as const).map((field) => (
                              <input
                                key={field}
                                type="text"
                                placeholder={field}
                                aria-label={`${field} for ${e.model_name}`}
                                value={overrides[e.model_id]?.[field] ?? ""}
                                onChange={(ev) => setOverride(e.model_id, { [field]: ev.target.value })}
                                className="bg-panel border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-start"
                              />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {loading && !preview && <div className="text-sm text-text-secondary-alt">Loading preview…</div>}

      {/* Apply / Undo */}
      <div className="pt-2 flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={runApply}
          disabled={busy || selected.size === 0}
          className={`px-4 py-2 rounded text-sm ${
            busy || selected.size === 0
              ? "bg-panel-secondary text-text-muted cursor-not-allowed"
              : "bg-accent-end text-white hover:bg-accent-start"
          }`}
        >
          {busy ? "Working…" : `Apply ${selected.size || ""}`.trim()}
        </button>
        {lastApply && (
          <button
            type="button"
            onClick={runUndo}
            disabled={busy}
            className="px-4 py-2 rounded text-sm bg-panel-secondary text-text-primary-alt hover:bg-panel-secondary disabled:opacity-50"
          >
            Undo last apply
          </button>
        )}
        {applyMsg && <span className="text-sm text-emerald-400">{applyMsg}</span>}
        {applyErr && <span className="text-sm text-rose-400">{applyErr}</span>}
      </div>
    </div>
  );
}
