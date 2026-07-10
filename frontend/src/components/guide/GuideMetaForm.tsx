import { useState } from "react";
import { X } from "lucide-react";
import {
  CreatorCredit,
  GuideCreateInput,
  GuideScale,
  GuideStatus,
  GuideTheme,
  PaintPill,
} from "../../api/client";
import ThemeEditor from "./ThemeEditor";

const SCALES: GuideScale[] = ["1:6", "1:12", "75mm", "28mm", "bust", "other"];
const STATUSES: GuideStatus[] = ["draft", "in_review", "published", "archived"];

export interface GuideMetaInitial {
  slug?: string;
  title?: string;
  title_lead?: string | null;
  subtitle?: string | null;
  category_label?: string | null;
  // Loose string: an existing Guide carries scale as a plain string. Coerced
  // against the known SCALES below; an unknown value falls back to "".
  scale?: string | null;
  status?: string;
  franchise?: string | null;
  quote?: string | null;
  creator_credit?: CreatorCredit | null;
  light_source?: string | null;
  philosophy_note?: string | null;
  paint_lines_used?: PaintPill[];
  technique_tags?: string[];
  theme?: GuideTheme | null;
}

interface Props {
  initial?: GuideMetaInitial;
  /** Hide the slug field when editing (slug changes are risky for links). */
  lockSlug?: boolean;
  submitLabel: string;
  busy?: boolean;
  /** Inline error surfaced from the API (e.g. 409 slug conflict). */
  error?: string | null;
  onSubmit: (value: GuideCreateInput) => void;
  onCancel: () => void;
}

const trimOrNull = (s: string): string | null => {
  const t = s.trim();
  return t === "" ? null : t;
};

// An all-empty theme is sent as null so new guides inherit the app default
// (#514) and edits don't persist a hollow object.
const normalizeTheme = (theme: GuideTheme | null): GuideTheme | null => {
  if (!theme) return null;
  const hasValue = Object.values(theme).some((v) => v != null && v !== "");
  return hasValue ? theme : null;
};

export default function GuideMetaForm({
  initial,
  lockSlug,
  submitLabel,
  busy,
  error,
  onSubmit,
  onCancel,
}: Props) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [titleLead, setTitleLead] = useState(initial?.title_lead ?? "");
  const [subtitle, setSubtitle] = useState(initial?.subtitle ?? "");
  const [categoryLabel, setCategoryLabel] = useState(initial?.category_label ?? "");
  const [scale, setScale] = useState<GuideScale | "">(
    SCALES.includes(initial?.scale as GuideScale) ? (initial?.scale as GuideScale) : ""
  );
  const [status, setStatus] = useState<GuideStatus>(
    STATUSES.includes(initial?.status as GuideStatus) ? (initial?.status as GuideStatus) : "draft"
  );
  const [franchise, setFranchise] = useState(initial?.franchise ?? "");
  const [quote, setQuote] = useState(initial?.quote ?? "");
  const [lightSource, setLightSource] = useState(initial?.light_source ?? "");
  const [philosophy, setPhilosophy] = useState(initial?.philosophy_note ?? "");
  const [creditName, setCreditName] = useState(initial?.creator_credit?.name ?? "");
  const [creditUrl, setCreditUrl] = useState(initial?.creator_credit?.url ?? "");
  const [creditLinkText, setCreditLinkText] = useState(initial?.creator_credit?.link_text ?? "");
  const [tags, setTags] = useState<string[]>(initial?.technique_tags ?? []);
  const [tagDraft, setTagDraft] = useState("");
  const [lines, setLines] = useState<PaintPill[]>(initial?.paint_lines_used ?? []);
  const [lineDraft, setLineDraft] = useState("");
  const [theme, setTheme] = useState<GuideTheme | null>(initial?.theme ?? null);
  const [missingTitle, setMissingTitle] = useState(false);

  const addTag = () => {
    const t = tagDraft.trim();
    if (t && !tags.includes(t)) setTags([...tags, t]);
    setTagDraft("");
  };
  const addLine = () => {
    const t = lineDraft.trim();
    if (t && !lines.some((l) => l.name === t)) setLines([...lines, { name: t }]);
    setLineDraft("");
  };

  const submit = () => {
    if (title.trim() === "") {
      setMissingTitle(true);
      return;
    }
    const credit: CreatorCredit | null =
      creditName.trim() || creditUrl.trim() || creditLinkText.trim()
        ? {
            name: trimOrNull(creditName),
            url: trimOrNull(creditUrl),
            link_text: trimOrNull(creditLinkText),
          }
        : null;
    // Slug is derived from the title when blank (create flow); the backend
    // requires a non-empty slug. Edits keep the existing slug (lockSlug).
    const finalSlug =
      slug.trim() ||
      title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    onSubmit({
      slug: finalSlug,
      title: title.trim(),
      title_lead: trimOrNull(titleLead),
      subtitle: trimOrNull(subtitle),
      category_label: trimOrNull(categoryLabel),
      scale: scale === "" ? null : scale,
      status,
      franchise: trimOrNull(franchise),
      quote: trimOrNull(quote),
      creator_credit: credit,
      light_source: trimOrNull(lightSource),
      philosophy_note: trimOrNull(philosophy),
      paint_lines_used: lines,
      technique_tags: tags,
      theme: normalizeTheme(theme),
    });
  };

  const field = "w-full bg-panel border border-border rounded px-3 py-2 text-sm text-text-primary focus:border-indigo-600 focus:outline-none";
  const labelCls = "block text-xs font-medium text-text-secondary mb-1";

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); submit(); }}
      className="space-y-5"
    >
      {error && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">
          {error}
        </p>
      )}

      <div>
        <label className={labelCls} htmlFor="guide-title">Title *</label>
        <input
          id="guide-title"
          className={field}
          value={title}
          onChange={(e) => { setTitle(e.target.value); setMissingTitle(false); }}
          placeholder="e.g. RoboCop (1987)"
        />
        {missingTitle && (
          <p role="alert" className="mt-1 text-xs text-rose-400">A title is required.</p>
        )}
      </div>

      {!lockSlug && (
        <div>
          <label className={labelCls} htmlFor="guide-slug">Slug</label>
          <input
            id="guide-slug"
            className={field}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="auto-generated from the title if left blank"
          />
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelCls} htmlFor="guide-lead">Title lead</label>
          <input id="guide-lead" className={field} value={titleLead} onChange={(e) => setTitleLead(e.target.value)} />
        </div>
        <div>
          <label className={labelCls} htmlFor="guide-subtitle">Subtitle</label>
          <input id="guide-subtitle" className={field} value={subtitle} onChange={(e) => setSubtitle(e.target.value)} />
        </div>
        <div>
          <label className={labelCls} htmlFor="guide-category">Category label</label>
          <input id="guide-category" className={field} value={categoryLabel} onChange={(e) => setCategoryLabel(e.target.value)} />
        </div>
        <div>
          <label className={labelCls} htmlFor="guide-franchise">Franchise</label>
          <input id="guide-franchise" className={field} value={franchise} onChange={(e) => setFranchise(e.target.value)} />
        </div>
        <div>
          <label className={labelCls} htmlFor="guide-scale">Scale</label>
          <select id="guide-scale" className={field} value={scale} onChange={(e) => setScale(e.target.value as GuideScale | "")}>
            <option value="">—</option>
            {SCALES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="guide-status">Status</label>
          <select id="guide-status" className={field} value={status} onChange={(e) => setStatus(e.target.value as GuideStatus)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="guide-light">Light source</label>
          <input id="guide-light" className={field} value={lightSource} onChange={(e) => setLightSource(e.target.value)} placeholder="e.g. zenithal, top-left" />
        </div>
      </div>

      <div>
        <label className={labelCls} htmlFor="guide-quote">Quote</label>
        <textarea id="guide-quote" rows={2} className={field} value={quote} onChange={(e) => setQuote(e.target.value)} />
      </div>

      <div>
        <label className={labelCls} htmlFor="guide-philosophy">Philosophy note</label>
        <textarea id="guide-philosophy" rows={3} className={field} value={philosophy} onChange={(e) => setPhilosophy(e.target.value)} />
      </div>

      <fieldset className="border border-border-subtle rounded p-3">
        <legend className="text-xs font-medium text-text-secondary px-1">Creator credit</legend>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className={labelCls} htmlFor="credit-name">Name</label>
            <input id="credit-name" className={field} value={creditName} onChange={(e) => setCreditName(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="credit-url">URL</label>
            <input id="credit-url" className={field} value={creditUrl} onChange={(e) => setCreditUrl(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="credit-linktext">Link text</label>
            <input id="credit-linktext" className={field} value={creditLinkText} onChange={(e) => setCreditLinkText(e.target.value)} />
          </div>
        </div>
      </fieldset>

      <div>
        <label className={labelCls} htmlFor="guide-tag-draft">Technique tags</label>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {tags.map((t) => (
            <span key={t} className="inline-flex items-center gap-1 text-xs bg-panel-secondary border border-border rounded px-2 py-0.5 text-text-primary-alt">
              #{t}
              <button type="button" aria-label={`Remove ${t}`} onClick={() => setTags(tags.filter((x) => x !== t))} className="text-text-secondary-alt hover:text-rose-400">
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
        <input
          id="guide-tag-draft"
          className={field}
          value={tagDraft}
          onChange={(e) => setTagDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
          placeholder="type a tag and press Enter"
        />
      </div>

      <div>
        <label className={labelCls} htmlFor="guide-line-draft">Paint lines used</label>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {lines.map((l) => (
            <span key={l.name} className="inline-flex items-center gap-1 text-xs bg-panel-secondary border border-border rounded px-2 py-0.5 text-text-primary-alt">
              {l.name}
              <button type="button" aria-label={`Remove ${l.name}`} onClick={() => setLines(lines.filter((x) => x.name !== l.name))} className="text-text-secondary-alt hover:text-rose-400">
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
        <input
          id="guide-line-draft"
          className={field}
          value={lineDraft}
          onChange={(e) => setLineDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLine(); } }}
          placeholder="e.g. Pro Acryl — press Enter"
        />
      </div>

      <details className="border border-border-subtle rounded">
        <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-text-primary-alt2">
          Theme
        </summary>
        <div className="px-3 pb-3 pt-1">
          <p className="text-xs text-text-secondary-alt mb-3">
            Customize this guide's colors. Leave fields blank to inherit the
            default theme from Settings.
          </p>
          <ThemeEditor value={theme} onChange={setTheme} />
        </div>
      </details>

      <div className="flex items-center gap-2 pt-2">
        <button
          type="submit"
          disabled={busy}
          className="inline-flex items-center gap-1.5 bg-accent-end hover:bg-accent-start text-white text-sm px-4 py-2 rounded transition-colors disabled:opacity-50"
        >
          {submitLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="text-sm text-text-secondary hover:text-text-primary-alt px-3 py-2"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
