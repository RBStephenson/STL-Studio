import { useState } from "react";
import { Plus, Trash2, FolderSearch } from "lucide-react";
import { useAppSettings } from "../../context/AppSettingsContext";
import HelpLink from "../../components/HelpLink";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";
import { errMsg } from "../../utils/err";

export default function ScanningTab() {
  const { settings, update } = useAppSettings();
  const { success, error, flash } = useSettingsFlash();
  const [newPattern, setNewPattern] = useState("");
  const [newKeyword, setNewKeyword] = useState("");
  const [newTag, setNewTag] = useState("");
  const [newPartsName, setNewPartsName] = useState("");

  const addIgnorePattern = async () => {
    const pat = newPattern.trim();
    if (!pat) return;
    const current = settings.scan_ignore_patterns;
    if (current.includes(pat)) { setNewPattern(""); return; }
    try {
      await update({ scan_ignore_patterns: [...current, pat] });
      setNewPattern("");
    } catch (e) {
      flash(errMsg(e) || "Could not add ignore pattern", "err");
    }
  };

  const removeIgnorePattern = async (pat: string) => {
    try {
      await update({ scan_ignore_patterns: settings.scan_ignore_patterns.filter((p) => p !== pat) });
    } catch (e) {
      flash(errMsg(e) || "Could not remove ignore pattern", "err");
    }
  };

  const addTagRule = async () => {
    const keyword = newKeyword.trim();
    const tag = newTag.trim();
    if (!keyword || !tag) return;
    const current = settings.scan_tag_rules;
    if (current.some((r) => r.keyword.toLowerCase() === keyword.toLowerCase() && r.tag.toLowerCase() === tag.toLowerCase())) {
      setNewKeyword(""); setNewTag(""); return;
    }
    try {
      await update({ scan_tag_rules: [...current, { keyword, tag }] });
      setNewKeyword(""); setNewTag("");
    } catch (e) {
      flash(errMsg(e) || "Could not add tag rule", "err");
    }
  };

  const removeTagRule = async (keyword: string, tag: string) => {
    try {
      await update({ scan_tag_rules: settings.scan_tag_rules.filter((r) => !(r.keyword === keyword && r.tag === tag)) });
    } catch (e) {
      flash(errMsg(e) || "Could not remove tag rule", "err");
    }
  };

  const addPartsName = async () => {
    const name = newPartsName.trim();
    if (!name) return;
    const current = settings.scan_parts_names;
    if (current.some((n) => n.toLowerCase() === name.toLowerCase())) { setNewPartsName(""); return; }
    try {
      await update({ scan_parts_names: [...current, name] });
      setNewPartsName("");
    } catch (e) {
      flash(errMsg(e) || "Could not add parts name", "err");
    }
  };

  const removePartsName = async (name: string) => {
    try {
      await update({ scan_parts_names: settings.scan_parts_names.filter((n) => n !== name) });
    } catch (e) {
      flash(errMsg(e) || "Could not remove parts name", "err");
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />

      {/* Ignore patterns */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <FolderSearch size={14} /> Scan Rules
          <HelpLink section="scan-rules" label="About scan rules" />
        </h2>
        <p className="text-xs text-text-muted mb-4">
          Folders matching an <strong className="text-text-secondary-alt">ignore pattern</strong> (and everything
          inside them) are skipped during scanning. Matching is case-insensitive against a folder's name
          (e.g. <code className="text-text-secondary-alt">WIP</code>) or its full path (e.g.{" "}
          <code className="text-text-secondary-alt">*/_archive/*</code>). Patterns take effect on the next scan;
          any already-indexed models they now cover are removed.
        </p>
        <div className="flex flex-col gap-2 self-start" data-testid="ignore-patterns">
          {settings.scan_ignore_patterns.length === 0 && (
            <p className="text-xs text-text-muted italic">No ignore patterns yet.</p>
          )}
          {settings.scan_ignore_patterns.map((pat) => (
            <div
              key={pat}
              className="flex items-center justify-between gap-3 bg-panel border border-border-subtle rounded-lg px-4 py-2 self-start min-w-[18rem]"
            >
              <code className="text-sm text-text-primary-alt">{pat}</code>
              <button
                onClick={() => removeIgnorePattern(pat)}
                aria-label={`Remove ${pat}`}
                className="text-text-secondary-alt hover:text-red-400 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <div className="flex items-center gap-2 mt-1">
            <input
              type="text"
              value={newPattern}
              onChange={(e) => setNewPattern(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addIgnorePattern(); } }}
              placeholder="e.g. WIP or */_archive/*"
              className="bg-panel border border-border rounded px-3 py-1.5 text-sm text-text-primary-alt placeholder-gray-600 focus:outline-none focus:border-accent-start w-64"
            />
            <button
              onClick={addIgnorePattern}
              disabled={!newPattern.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded bg-accent-end text-white hover:bg-accent-start disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Plus size={14} /> Add
            </button>
          </div>
        </div>
      </section>

      {/* Tag rules */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1">
          Tag Rules
        </h2>
        <p className="text-xs text-text-muted mb-4">
          <strong className="text-text-secondary-alt">Tag rules</strong> add an auto-tag to any model whose
          name contains a keyword — e.g. keyword <code className="text-text-secondary-alt">Aztec</code> →
          tag <code className="text-text-secondary-alt">civ</code>. These add to the built-in tag detection and
          apply on the next full scan; they don't affect how variants group.
        </p>
        <div className="flex flex-col gap-2 self-start" data-testid="tag-rules">
          {settings.scan_tag_rules.length === 0 && (
            <p className="text-xs text-text-muted italic">No tag rules yet.</p>
          )}
          {settings.scan_tag_rules.map((r) => (
            <div
              key={`${r.keyword} ${r.tag}`}
              className="flex items-center justify-between gap-3 bg-panel border border-border-subtle rounded-lg px-4 py-2 self-start min-w-[18rem]"
            >
              <span className="text-sm text-text-primary-alt">
                <code>{r.keyword}</code>
                <span className="text-text-muted mx-2">&rarr;</span>
                <code className="text-indigo-300">{r.tag}</code>
              </span>
              <button
                onClick={() => removeTagRule(r.keyword, r.tag)}
                aria-label={`Remove ${r.keyword} to ${r.tag}`}
                className="text-text-secondary-alt hover:text-red-400 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <div className="flex items-center gap-2 mt-1">
            <input
              type="text"
              value={newKeyword}
              onChange={(e) => setNewKeyword(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTagRule(); } }}
              placeholder="keyword (e.g. Aztec)"
              className="bg-panel border border-border rounded px-3 py-1.5 text-sm text-text-primary-alt placeholder-gray-600 focus:outline-none focus:border-accent-start w-44"
            />
            <span className="text-text-muted">&rarr;</span>
            <input
              type="text"
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTagRule(); } }}
              placeholder="tag (e.g. civ)"
              className="bg-panel border border-border rounded px-3 py-1.5 text-sm text-text-primary-alt placeholder-gray-600 focus:outline-none focus:border-accent-start w-44"
            />
            <button
              onClick={addTagRule}
              disabled={!newKeyword.trim() || !newTag.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded bg-accent-end text-white hover:bg-accent-start disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Plus size={14} /> Add
            </button>
          </div>
        </div>
      </section>

      {/* Parts folder names */}
      <section>
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1">
          Parts Folder Names
        </h2>
        <p className="text-xs text-text-muted mb-4">
          <strong className="text-text-secondary-alt">Parts folder names</strong> are exact folder names
          treated as parts/structure (e.g. <code className="text-text-secondary-alt">Sprues</code>,{" "}
          <code className="text-text-secondary-alt">Magnets</code>) — never indexed as their own model and
          never used to group variants. These add to the built-in names (Parts, Base, Supports…)
          and apply on the next full scan.
        </p>
        <div className="flex flex-col gap-2 self-start" data-testid="parts-names">
          {settings.scan_parts_names.length === 0 && (
            <p className="text-xs text-text-muted italic">No custom parts names yet.</p>
          )}
          {settings.scan_parts_names.map((name) => (
            <div
              key={name}
              className="flex items-center justify-between gap-3 bg-panel border border-border-subtle rounded-lg px-4 py-2 self-start min-w-[18rem]"
            >
              <code className="text-sm text-text-primary-alt">{name}</code>
              <button
                onClick={() => removePartsName(name)}
                aria-label={`Remove ${name}`}
                className="text-text-secondary-alt hover:text-red-400 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <div className="flex items-center gap-2 mt-1">
            <input
              type="text"
              value={newPartsName}
              onChange={(e) => setNewPartsName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addPartsName(); } }}
              placeholder="e.g. Sprues"
              className="bg-panel border border-border rounded px-3 py-1.5 text-sm text-text-primary-alt placeholder-gray-600 focus:outline-none focus:border-accent-start w-64"
            />
            <button
              onClick={addPartsName}
              disabled={!newPartsName.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded bg-accent-end text-white hover:bg-accent-start disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Plus size={14} /> Add
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
