import { useState, useEffect } from "react";
import { Save, X, Loader2, Download, CheckCircle, AlertCircle } from "lucide-react";
import { api, ModelDetail, ScrapePreview } from "../api/client";
import TagInput from "./TagInput";

interface Props {
  model: ModelDetail;
  onSaved: () => void;
  onCancel: () => void;
}

const SITES = ["myminifactory", "gumroad", "cults3d", "printables", "thingiverse", "thangs", "makerworld", "patreon", "other"];

// Defined at module scope (NOT inside the component) so its identity is stable
// across renders. Defining it inside would create a new component type on every
// keystroke, remounting the inputs and dropping focus after each character.
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</label>
      {children}
    </div>
  );
}

export default function MetadataEditor({ model, onSaved, onCancel }: Props) {
  const [form, setForm] = useState({
    title:         model.title        ?? "",
    description:   model.description  ?? "",
    notes:         model.notes        ?? "",
    source_url:    model.source_url   ?? "",
    source_site:   model.source_site  ?? "",
    license:       model.license      ?? "",
    category:      model.category     ?? "",
    creator_name:  model.creator?.name ?? "",
    tags:          model.tags         ?? [],
    nsfw:          model.nsfw         ?? false,
    thumbnail_url: model.thumbnail_url ?? "",
  });

  const [tagSuggestions, setTagSuggestions] = useState<{ tag: string; count: number }[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [scraped, setScraped] = useState<ScrapePreview | null>(null);

  useEffect(() => {
    api.models.tags().then(setTagSuggestions).catch(() => {});
  }, []);

  const set = (key: string, value: unknown) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.models.update(model.id, form);
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const fetchMetadata = async () => {
    if (!form.source_url) return;
    setFetching(true);
    setFetchError(null);
    setScraped(null);
    try {
      const preview = await api.scrape.fetchUrl(form.source_url);
      setScraped(preview);
    } catch (e: any) {
      setFetchError(e.message.includes("400") ? "URL not recognised — only Gumroad, Cults3D and MyMiniFactory are supported." : "Could not fetch metadata from that URL.");
    } finally {
      setFetching(false);
    }
  };

  const applyScraped = () => {
    if (!scraped) return;
    setForm((prev) => ({
      ...prev,
      title:         scraped.title         || prev.title,
      description:   scraped.description   || prev.description,
      source_url:    scraped.source_url    || prev.source_url,
      source_site:   scraped.source_site   || prev.source_site,
      license:       scraped.license       || prev.license,
      category:      scraped.category      || prev.category,
      creator_name:  scraped.creator_name  || prev.creator_name,
      thumbnail_url: scraped.thumbnail_url || prev.thumbnail_url,
      tags:          [...new Set([...prev.tags, ...scraped.tags])],
    }));
    setScraped(null);
  };

  const inputClass =
    "bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition-colors";

  return (
    <div className="flex flex-col gap-5 bg-gray-900/50 border border-gray-800 rounded-xl p-5">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-200">Edit Metadata</h3>
        <button onClick={onCancel} className="text-gray-600 hover:text-gray-400">
          <X size={16} />
        </button>
      </div>

      <Field label="Title">
        <input
          type="text"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder={model.name}
          className={inputClass}
        />
      </Field>

      <Field label="Creator">
        <input
          type="text"
          value={form.creator_name}
          onChange={(e) => set("creator_name", e.target.value)}
          className={inputClass}
        />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Source Site">
          <select
            value={form.source_site}
            onChange={(e) => set("source_site", e.target.value)}
            className={inputClass}
          >
            <option value="">Unknown</option>
            {SITES.map((s) => (
              <option key={s} value={s} className="capitalize">{s}</option>
            ))}
          </select>
        </Field>
        <Field label="License">
          <input
            type="text"
            value={form.license}
            onChange={(e) => set("license", e.target.value)}
            placeholder="e.g. CC BY-NC"
            className={inputClass}
          />
        </Field>
      </div>

      <Field label="Source URL">
        <div className="flex gap-2">
          <input
            type="url"
            value={form.source_url}
            onChange={(e) => { set("source_url", e.target.value); setScraped(null); setFetchError(null); }}
            placeholder="https://…"
            className={`${inputClass} flex-1`}
          />
          <button
            type="button"
            onClick={fetchMetadata}
            disabled={fetching || !form.source_url}
            title="Fetch metadata from this URL"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 text-sm text-white transition-colors shrink-0"
          >
            {fetching ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Fetch
          </button>
        </div>
        {fetchError && (
          <p className="flex items-center gap-1.5 text-xs text-red-400 mt-1">
            <AlertCircle size={12} /> {fetchError}
          </p>
        )}
        {scraped && (
          <div className="mt-2 flex gap-3 p-3 bg-gray-800 border border-indigo-700 rounded-lg">
            {scraped.thumbnail_url && (
              <img src={scraped.thumbnail_url} alt="" className="w-16 h-16 object-cover rounded shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-100 truncate">{scraped.title}</p>
              {scraped.creator_name && <p className="text-xs text-gray-400">by {scraped.creator_name}</p>}
              {scraped.tags.length > 0 && (
                <p className="text-xs text-gray-500 mt-0.5">Tags: {scraped.tags.join(", ")}</p>
              )}
            </div>
            <button
              type="button"
              onClick={applyScraped}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-xs text-white shrink-0 self-start transition-colors"
            >
              <CheckCircle size={12} /> Apply
            </button>
          </div>
        )}
      </Field>

      <Field label="Category">
        <input
          type="text"
          value={form.category}
          onChange={(e) => set("category", e.target.value)}
          placeholder="e.g. Figures, Busts, Terrain…"
          className={inputClass}
        />
      </Field>

      {/* NSFW toggle */}
      <label className="flex items-center gap-3 cursor-pointer select-none">
        <div
          onClick={() => set("nsfw", !form.nsfw)}
          className={`relative w-10 h-6 rounded-full transition-colors ${
            form.nsfw ? "bg-red-600" : "bg-gray-700"
          }`}
        >
          <span
            className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow transition-transform ${
              form.nsfw ? "translate-x-5" : "translate-x-1"
            }`}
          />
        </div>
        <div>
          <p className="text-sm text-gray-300 font-medium">NSFW</p>
          <p className="text-xs text-gray-600">Blurs thumbnail in the library grid</p>
        </div>
      </label>

      <Field label="Tags">
        <TagInput
          value={form.tags}
          onChange={(tags) => set("tags", tags)}
          suggestions={tagSuggestions}
        />
      </Field>

      <Field label="Description">
        <textarea
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          rows={4}
          className={`${inputClass} resize-y`}
        />
      </Field>

      <Field label="Notes (private)">
        <textarea
          value={form.notes}
          onChange={(e) => set("notes", e.target.value)}
          rows={2}
          placeholder="Your personal notes about this model…"
          className={`${inputClass} resize-y`}
        />
      </Field>

      {error && (
        <p className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded px-3 py-2">
          {error}
        </p>
      )}

      <div className="flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm transition-colors"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save
        </button>
      </div>
    </div>
  );
}
