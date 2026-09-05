import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FocusEvent, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { TemplatePreviewResponse } from "../../api/client";

// The one frontend definition (STUDIO-402). ReorganizePage used to declare its
// own and the Settings field hard-coded the same string as a placeholder, which
// made three copies counting the backend's `reorganize_template.DEFAULT_TEMPLATE`
// — both frontend copies now import this one.
export const DEFAULT_TEMPLATE = "{creator}/{character}/{title}";

const PREVIEW_DEBOUNCE_MS = 400;

const TOKENS = ["{creator}", "{character}", "{scale}", "{title}"] as const;

// UI-only sugar: selecting one just fills the field, which stays editable.
// Deliberately NOT a stored concept — nothing about a preset is persisted.
//
// The scale preset ships `{scale?}`, not `{scale}`, on purpose: scale comes from
// scanner auto-tags that most models don't carry, so a required `{scale}` blocks
// most of a library at once. A one-click preset is exactly the wrong place to
// hand someone that.
const PRESETS: { label: string; template: string; hint: string }[] = [
  {
    label: "Creator → Character → Title",
    template: DEFAULT_TEMPLATE,
    hint: "The default layout.",
  },
  {
    label: "Creator → Title",
    template: "{creator}/{title}",
    hint: "Flat: every model sits directly under its creator.",
  },
  {
    label: "Creator → Scale → Character → Title",
    template: "{creator}/{scale?}/{character}/{title}",
    hint: "Adds a scale level, skipped for models with no detected scale.",
  },
  {
    label: "Creator → Character",
    template: "{creator}/{character}",
    hint: "Matches how package preservation places files.",
  },
];

interface Props {
  value: string;
  onChange: (next: string) => void;
  /** Called once focus leaves the whole editor. Settings persists here; the
   *  Reorganize page passes nothing, because its field is a one-off that is
   *  deliberately never saved. */
  onCommit?: () => void;
  /** Limits the live example to one scan root (Reorganize page only). */
  rootId?: number;
  /** Says whether this field is saved or applies to one plan — the distinction
   *  existed in the code but nothing in the UI ever said so. */
  scopeNote: ReactNode;
}

/** Destination-template editor: token chips, presets, inline validation, and a
 *  live example rendered against real models (STUDIO-402).
 *
 *  The example comes from `/reorganize/template-preview`, which does no
 *  filesystem work at all — that is what makes it cheap enough to re-run as the
 *  user types. The flip side, and the thing this component must never blur: its
 *  flags cover only what the TEMPLATE caused. Locks, symlinks, collisions,
 *  missing files and multi-directory models all need the disk, so a clean
 *  example is NOT a promise that a model will move. Only a built plan says that.
 */
export default function TemplateEditor({ value, onChange, onCommit, rootId, scopeNote }: Props) {
  const [preview, setPreview] = useState<TemplatePreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Caret position to restore after a chip/preset rewrites a controlled input —
  // without this the caret jumps to the end on every insert.
  const caretRef = useRef<number | null>(null);

  useLayoutEffect(() => {
    if (caretRef.current !== null && inputRef.current) {
      inputRef.current.setSelectionRange(caretRef.current, caretRef.current);
      caretRef.current = null;
    }
  });

  const trimmed = value.trim();

  useEffect(() => {
    // A blank template makes the server fall back to the SAVED one, so previewing
    // it would confidently render a template the user isn't looking at. Say
    // nothing instead of saying the wrong thing.
    if (!trimmed) {
      setPreview(null);
      setError(null);
      setBusy(false);
      return;
    }
    let cancelled = false;
    setBusy(true);
    const timer = setTimeout(async () => {
      try {
        const data = await api.reorganize.templatePreview(trimmed, rootId);
        if (!cancelled) {
          setPreview(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          // The endpoint returns the real parse message on a 400, so the user
          // gets "unknown token {creater}" rather than a generic failure. The
          // field itself is never cleared — losing what they typed is worse than
          // an invalid template sitting there.
          setPreview(null);
          setError(e instanceof ApiError ? e.message : "Could not render this template");
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [trimmed, rootId]);

  const replaceSelection = (text: string) => {
    const el = inputRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    caretRef.current = start + text.length;
    onChange(value.slice(0, start) + text + value.slice(end));
  };

  const applyPreset = (template: string) => {
    caretRef.current = template.length;
    onChange(template);
    inputRef.current?.focus();
  };

  // Committing on the input's own blur would fire every time a chip is clicked,
  // saving a half-typed template mid-edit. Commit only once focus has left the
  // editor entirely.
  const handleBlur = (e: FocusEvent<HTMLDivElement>) => {
    if (!onCommit) return;
    if (e.currentTarget.contains(e.relatedTarget)) return;
    onCommit();
  };

  return (
    <div className="space-y-2" onBlur={handleBlur}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-text-secondary-alt mr-0.5">Insert</span>
        {TOKENS.map((token) => (
          <button
            key={token}
            type="button"
            // Keeps focus (and the caret) in the input, so a mouse user never
            // sees the insertion point jump.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => replaceSelection(token)}
            title={`Insert ${token} at the cursor`}
            className="px-2 py-0.5 rounded bg-panel-secondary border border-border text-xs font-mono text-indigo-300 hover:text-indigo-200 hover:border-accent-start"
          >
            {token}
          </button>
        ))}
      </div>

      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
        spellCheck={false}
        aria-label="Destination template"
        className="w-full bg-panel border border-border rounded px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:border-accent-start"
      />

      <div className="text-xs text-text-secondary-alt">
        Separate levels with <code>/</code>. Add <code>?</code> to make a token optional
        (<code className="text-indigo-400">{"{scale?}"}</code>): its level is skipped for
        models with no value, instead of blocking them.
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-text-secondary-alt mr-0.5">Start from</span>
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => applyPreset(preset.template)}
            title={`${preset.template} — ${preset.hint}`}
            aria-pressed={trimmed === preset.template}
            className={`px-2 py-0.5 rounded border text-xs ${
              trimmed === preset.template
                ? "bg-accent-start border-accent-start text-white"
                : "bg-panel-secondary border-border text-text-primary-alt2 hover:text-text-primary"
            }`}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <p className="text-xs text-text-muted">{scopeNote}</p>

      {error && <div className="text-xs text-rose-400">{error}</div>}

      {!trimmed && (
        <div className="text-xs text-amber-400">
          The template is empty — insert a token above to see where models would go.
        </div>
      )}

      {trimmed && !error && (
        <div className="rounded-lg border border-border-subtle bg-panel/60 px-3 py-2 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-text-primary-alt2">Example destinations</span>
            {busy && (
              <span className="flex items-center gap-1 text-xs text-text-secondary-alt">
                <Loader2 size={11} className="animate-spin" /> Rendering…
              </span>
            )}
          </div>

          {preview?.package_mode && (
            <div className="text-xs text-amber-300">
              Package preservation is on, so this template does not decide placement:
              Reorganize normalizes the <code className="font-mono">{"{creator}/{character}"}</code>{" "}
              prefix and keeps each release package's own name and internal folders unchanged.
              These examples are advisory only.
            </div>
          )}

          {preview && preview.samples.length === 0 && (
            <div className="text-xs text-text-muted">
              No models to render against yet — scan a library first.
            </div>
          )}

          {preview?.samples.map((s) => (
            <div key={s.model_id} className="text-xs space-y-0.5">
              <div className="text-text-primary-alt truncate" title={s.model_name}>{s.model_name}</div>
              <div className="font-mono text-text-muted truncate" title={s.source_dir}>{s.source_dir}</div>
              <div className="font-mono text-text-secondary truncate" title={s.proposed_dir}>
                → {s.proposed_dir}
              </div>
              <div className="flex flex-wrap gap-1">
                {s.unclassifiable && (
                  <span className="px-1.5 py-0.5 rounded bg-amber-950 text-amber-300">
                    {s.missing_fields.length
                      ? `no ${s.missing_fields.join(", ")}`
                      : "missing a value this template needs"}
                  </span>
                )}
                {s.over_length && (
                  <span className="px-1.5 py-0.5 rounded bg-amber-950 text-amber-300">too long</span>
                )}
                {s.reserved_name && (
                  <span className="px-1.5 py-0.5 rounded bg-amber-950 text-amber-300">reserved name</span>
                )}
              </div>
            </div>
          ))}

          {/* The inherited constraint from STUDIO-401, and the easiest thing here
              to get quietly wrong: these samples answer "where does the template
              put this", never "will this move". */}
          <p className="text-xs text-text-muted border-t border-border-subtle pt-2">
            Template rendering only — this does not say whether a model can move.
            Collisions, locks, symlinks and missing files need a built plan.
          </p>
        </div>
      )}
    </div>
  );
}
