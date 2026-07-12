import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, RefreshCw, Square, AlertCircle } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
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

// Tabs mix two dimensions: what KIND of change an entry needs (Moves,
// Already In Place) and WHY it can't proceed yet (Collisions, Unclassifiable,
// Blocked) — so a row can land in more than one tab, e.g. a would-be move
// that's also a collision shows under Collisions and Blocked, not Moves,
// until the collision is resolved. Hints spell this out (STUDIO-164).
const FILTERS: { key: FilterTab; label: string; hint: string }[] = [
  { key: "all", label: "All", hint: "Every model in this preview" },
  { key: "moves", label: "Moves", hint: "Will move or rename on Apply right now — blocked movers show under Collisions/Unclassifiable/Blocked instead until resolved" },
  { key: "collisions", label: "Collisions", hint: "Proposed destination collides with another model or file" },
  { key: "unclassifiable", label: "Unclassifiable", hint: "Missing a value (e.g. character) the template needs — resolve it below" },
  { key: "blocked", label: "Blocked", hint: "Can't be applied for any reason — collision, unclassifiable, over-length, locked, etc." },
  { key: "in_place", label: "Already In Place", hint: "Already matches the destination template — nothing to do" },
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
    // Only entries that will actually move on Apply right now — a move-kind
    // entry that's still blocked belongs under Blocked/Collisions/
    // Unclassifiable instead (STUDIO-164).
    case "moves": return ["move", "rename", "case_rename"].includes(e.kind) && e.eligible;
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
  const seededExpand = useRef(false);
  const { toast } = useToast();

  // Scanning is a deliberate, user-triggered action (STUDIO-155) — nothing
  // fetches until the user clicks Build/Retry/Rebuild. `runToken` bumps on
  // each of those triggers; the debounced effect below only fires once
  // `started` is true, so template/override edits still auto-refresh an
  // *existing* plan without the page auto-scanning on mount.
  const [started, setStarted] = useState(false);
  const [runToken, setRunToken] = useState(0);
  const cancelledRef = useRef(false);
  const runReorgScan = () => { cancelledRef.current = false; setStarted(true); setRunToken((t) => t + 1); };
  const cancelReorgScan = () => { cancelledRef.current = true; setLoading(false); setStarted(false); };

  const hasOverrides = Object.keys(overrides).length > 0;

  useEffect(() => {
    if (!started) return;
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = hasOverrides
          ? await api.reorganize.previewWithOverrides({ template, overrides })
          : await api.reorganize.preview(template);
        if (!cancelled && !cancelledRef.current) {
          setPreview(data); setError(null);
          toast("Reorganize plan ready.", "success");
        }
      } catch (e) {
        if (!cancelled && !cancelledRef.current) {
          setError(e instanceof ApiError ? e.message : "Failed to load preview");
          if (e instanceof ApiError && e.status === 400) setPreview(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, template, overrides, hasOverrides, runToken]);

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

  // Auto-expand blocked-but-resolvable rows on the first preview so the Resolve
  // fields are visible without the user having to discover the row is
  // clickable (STUDIO-170). Only seeds once per mount — later re-previews
  // (e.g. from typing an override) don't fight a user's manual collapse.
  useEffect(() => {
    if (preview && !seededExpand.current) {
      seededExpand.current = true;
      setExpanded(new Set(
        preview.entries.filter((e) => !e.eligible && isResolvable(e)).map((e) => e.model_id),
      ));
    }
  }, [preview]);

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
          Nothing is scanned until you build a plan. Building only reads your
          library; applying is a separate, explicit step.
        </p>
      </div>

      {/* Template editor */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-text-primary-alt2">
          Destination template
          {loading && preview && (
            <span className="flex items-center gap-1 text-xs text-text-secondary-alt">
              <Loader2 size={12} className="animate-spin" /> Updating preview…
            </span>
          )}
        </label>
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
        {error && preview && <div className="text-sm text-rose-400">{error}</div>}
      </div>

      {!started && !loading && (
        <div className="flex flex-col items-center justify-center text-center py-14 px-8 border border-dashed border-border-subtle rounded-xl bg-panel/40">
          <div className="w-13 h-13 rounded-full bg-indigo-950/60 flex items-center justify-center mb-4" style={{ width: 52, height: 52 }}>
            <RefreshCw size={22} className="text-indigo-400" />
          </div>
          <p className="text-sm font-semibold text-text-primary mb-1">No plan yet</p>
          <p className="text-sm text-text-secondary-alt max-w-sm mb-4">
            Build a plan to see proposed moves against your template above. This reads
            your library only — no files move until you apply.
          </p>
          <button
            type="button"
            onClick={runReorgScan}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-accent-end hover:bg-accent-start text-white text-sm font-semibold transition-colors"
          >
            <RefreshCw size={14} /> Build Reorganize Plan
          </button>
        </div>
      )}

      {loading && !preview && (
        <div className="flex items-center gap-3.5 bg-indigo-950/20 border border-indigo-900/50 rounded-xl px-4 py-4">
          <Loader2 size={18} className="animate-spin text-indigo-400 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-text-primary">Building reorganize plan…</p>
            <p className="text-xs text-text-secondary-alt mt-0.5">
              Scanning your library against the destination template. This can take a
              few minutes on large libraries.
            </p>
          </div>
          <button
            type="button"
            onClick={cancelReorgScan}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-panel-secondary border border-border text-text-primary-alt2 text-xs shrink-0"
          >
            <Square size={11} /> Cancel
          </button>
        </div>
      )}

      {!loading && error && !preview && (
        <div className="flex flex-col items-center justify-center text-center py-14 px-8 border border-dashed border-rose-900/40 rounded-xl bg-rose-950/10">
          <div className="w-13 h-13 rounded-full bg-rose-950/40 flex items-center justify-center mb-4" style={{ width: 52, height: 52 }}>
            <AlertCircle size={22} className="text-rose-300" />
          </div>
          <p className="text-sm font-semibold text-text-primary mb-1">Couldn't build the plan</p>
          <p className="text-sm text-text-secondary-alt max-w-sm mb-4">{error}</p>
          <button
            type="button"
            onClick={runReorgScan}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-accent-end hover:bg-accent-start text-white text-sm font-semibold transition-colors"
          >
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      )}

      {preview && (
        <>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={runReorgScan}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-panel-secondary border border-border text-text-primary-alt2 text-xs"
            >
              <RefreshCw size={11} /> Rebuild Plan
            </button>
          </div>
          <ReorganizeStatsBar stats={preview.stats} />

          {/* Filter tabs */}
          <div className="flex gap-1 flex-wrap border-b border-border-subtle">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setTab(f.key)}
                title={f.hint}
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
                    {!e.eligible && isResolvable(e) && !isOpen && (
                      <span className="text-xs px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 shrink-0">
                        click to resolve
                      </span>
                    )}
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
