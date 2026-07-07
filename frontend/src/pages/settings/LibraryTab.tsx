import { useState, useRef } from "react";
import { Link } from "react-router-dom";
import { HardDrive, Plus, Trash2, FolderSearch, FolderTree, RefreshCw } from "lucide-react";
import { api, ScanRoot } from "../../api/client";
import FolderPicker from "../../components/FolderPicker";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";
import { errMsg } from "../../utils/err";
import { useAppSettings } from "../../context/AppSettingsContext";

const LAYOUT_SAMPLES: Record<string, string> = {
  "{creator}": "Abe3D",
  "{tag}": "Sci-Fi",
  "{ignore}": "_misc",
  "*": "_misc",
};

function layoutPreview(template: string): string | null {
  const segs = (template.trim() || "{creator}")
    .replace(/^[/\\]+|[/\\]+$/g, "")
    .split(/[/\\]+/)
    .filter(Boolean);
  if (segs.length === 0) return null;
  if (segs.filter((s) => s === "{creator}").length !== 1) return null;
  if (segs[segs.length - 1] !== "{creator}") return null;
  const parts = segs.map((s) => {
    const sample = LAYOUT_SAMPLES[s];
    if (!sample) return null;
    const role = s === "*" ? "ignore" : s.replace(/[{}]/g, "");
    return `${sample} (${role})`;
  });
  if (parts.some((p) => p === null)) return null;
  return [...parts, "…models"].join(" › ");
}

const PATH_EXAMPLES: Record<string, string[]> = {
  Windows: ["D:\\3D STLs", "E:\\My Models"],
  macOS: ["/Volumes/MyDrive/3D STLs"],
  Linux: ["/media/username/MyDrive/STLs", "/mnt/nas/models"],
};

interface Props {
  roots: ScanRoot[];
  loading: boolean;
  onRootsChanged: () => void;
}

export default function LibraryTab({ roots, loading, onRootsChanged }: Props) {
  const { success, error, flash } = useSettingsFlash();
  const { settings, update } = useAppSettings();
  const [newPath, setNewPath] = useState("");
  const [newLayout, setNewLayout] = useState("{creator}");
  const [layoutEdits, setLayoutEdits] = useState<Record<number, string>>({});
  const [nameEdits, setNameEdits] = useState<Record<number, string>>({});
  const [picking, setPicking] = useState(false);
  const [reloadingEnv, setReloadingEnv] = useState(false);
  const [templateEdit, setTemplateEdit] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const saveReorganizeTemplate = async () => {
    const next = (templateEdit ?? settings.reorganize_template).trim();
    if (next === settings.reorganize_template) { setTemplateEdit(null); return; }
    try {
      await update({ reorganize_template: next });
      setTemplateEdit(null);
      flash("Reorganize template updated", "ok");
    } catch (e) {
      flash(errMsg(e) || "Invalid reorganize template — check the format", "err");
    }
  };

  const addRoot = async (pathArg?: string) => {
    const path = (pathArg ?? newPath).trim();
    if (!path) return;
    try {
      await api.scan.addRoot(path, newLayout.trim() || "{creator}");
      setNewPath("");
      setNewLayout("{creator}");
      onRootsChanged();
      flash("Drive added — run a scan to index it", "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not add drive", "err");
    }
  };

  const saveLayout = async (root: ScanRoot) => {
    const next = (layoutEdits[root.id] ?? root.layout).trim() || "{creator}";
    const clearEdit = () =>
      setLayoutEdits((m) => { const copy = { ...m }; delete copy[root.id]; return copy; });
    if (next === root.layout) { clearEdit(); return; }
    try {
      await api.scan.updateRoot(root.id, { layout: next });
      clearEdit();
      onRootsChanged();
      flash("Layout updated — rescan to apply it", "ok");
    } catch (e) {
      flash(errMsg(e) || "Invalid layout template — check the format", "err");
    }
  };

  const saveName = async (root: ScanRoot) => {
    const next = (nameEdits[root.id] ?? root.name ?? "").trim();
    const clearEdit = () =>
      setNameEdits((m) => { const copy = { ...m }; delete copy[root.id]; return copy; });
    if (next === (root.name ?? "")) { clearEdit(); return; }
    try {
      await api.scan.updateRoot(root.id, { name: next });
      clearEdit();
      onRootsChanged();
      flash("Library name updated", "ok");
    } catch (e) {
      flash(errMsg(e) || "Couldn't update the library name", "err");
    }
  };

  const toggleWritable = async (root: ScanRoot) => {
    try {
      await api.scan.updateRoot(root.id, { is_writable: !root.is_writable });
      onRootsChanged();
      flash(root.is_writable ? "No longer an import destination" : "Marked as an import destination", "ok");
    } catch (e) {
      flash(errMsg(e) || "Couldn't update the library", "err");
    }
  };

  const toggleGroupByCharacter = async (root: ScanRoot) => {
    try {
      await api.scan.updateRoot(root.id, { group_by_character: !root.group_by_character });
      onRootsChanged();
      flash(
        root.group_by_character
          ? "Grouping by character folder off — rescan to apply"
          : "Grouping by character folder on — rescan to apply",
        "ok",
      );
    } catch (e) {
      flash(errMsg(e) || "Couldn't update the library", "err");
    }
  };

  const removeRoot = async (id: number, path: string) => {
    if (!confirm(`Remove "${path}" from the library?\n\nThis won't delete any files — just removes it from scanning.`)) return;
    try {
      await api.scan.removeRoot(id);
      onRootsChanged();
      flash("Drive removed", "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not remove drive", "err");
    }
  };

  const reloadEnv = async () => {
    setReloadingEnv(true);
    try {
      const res = await api.settings.reloadEnv();
      onRootsChanged();
      const restart = res.restart_required.length
        ? ` (${res.restart_required.join(", ")} still need a restart)`
        : "";
      flash(`Settings reloaded from .env${restart}`, "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not reload settings", "err");
    } finally {
      setReloadingEnv(false);
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />

      {/* Add new root */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Add a Folder
        </h2>
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addRoot(); }}
            placeholder="Full path to your STL folder…"
            className="flex-1 bg-gray-900 border border-gray-700 focus:border-indigo-500 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none font-mono"
          />
          <button
            onClick={() => setPicking(true)}
            title="Browse for a folder"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-sm transition-colors"
          >
            <FolderSearch size={15} />
            Browse…
          </button>
          <button
            onClick={() => newPath.trim() ? addRoot() : setPicking(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm transition-colors"
          >
            <Plus size={15} />
            Add Folder
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          Use <strong className="text-gray-500">Browse…</strong> to pick a folder, or type the full path. Subfolders are scanned automatically.
        </p>

        <div className="bg-gray-900/60 border border-gray-800 rounded-lg px-4 py-3 mt-4">
          <p className="text-xs text-gray-400 mb-2">
            A <strong className="text-gray-300">layout</strong> tells STL Studio how the folders
            above each model map to a <span className="text-indigo-300">creator</span> and{" "}
            <span className="text-emerald-300">tags</span>. Read each path left to right, one folder
            per <code className="text-gray-500">/</code>:
          </p>
          <div className="font-mono text-xs bg-gray-950 border border-gray-800 rounded px-3 py-2 mb-2 overflow-x-auto">
            <span className="text-gray-500">D:\3D STLs\</span>
            <span className="text-emerald-300">Sci-Fi</span>
            <span className="text-gray-600">\</span>
            <span className="text-indigo-300">Abe3D</span>
            <span className="text-gray-600">\</span>
            <span className="text-amber-300">Space Marine</span>
            <span className="text-gray-600">\model.stl</span>
          </div>
          <p className="text-xs text-gray-500 leading-relaxed">
            With the layout <code className="text-gray-400">{"{tag}/{creator}"}</code>, the example above
            tags the model <span className="text-emerald-300">Sci-Fi</span>, credits it to creator{" "}
            <span className="text-indigo-300">Abe3D</span>, and treats{" "}
            <span className="text-amber-300">Space Marine</span> as the model folder.
            Tokens: <code className="text-gray-400">{"{creator}"}</code> (required, last level),{" "}
            <code className="text-gray-400">{"{tag}"}</code> (tag with folder name),{" "}
            <code className="text-gray-400">{"{ignore}"}</code> (skip a level).
          </p>
        </div>

        <div className="mt-4">
          <label className="block text-xs text-gray-500 mb-1">Folder layout</label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newLayout}
              onChange={(e) => setNewLayout(e.target.value)}
              spellCheck={false}
              placeholder="{creator}"
              className="w-64 bg-gray-900 border border-gray-700 focus:border-indigo-500 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none font-mono"
            />
            <span className={`text-xs truncate ${layoutPreview(newLayout) ? "text-gray-500" : "text-amber-400"}`}>
              {layoutPreview(newLayout) ?? "needs exactly one {creator}, as the last level"}
            </span>
          </div>
        </div>
      </section>

      {/* Path examples */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Path Examples
        </h2>
        <div className="flex flex-col gap-3">
          {Object.entries(PATH_EXAMPLES).map(([os, paths]) => (
            <div key={os}>
              <p className="text-xs text-gray-500 mb-1">{os}</p>
              <div className="flex flex-col gap-1">
                {paths.map((p) => (
                  <button
                    key={p}
                    onClick={() => { setNewPath(p); inputRef.current?.focus(); }}
                    className="text-left text-xs font-mono text-gray-400 hover:text-indigo-300 bg-gray-900 border border-gray-800 hover:border-indigo-700 rounded px-3 py-1.5 transition-colors"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Current roots */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <HardDrive size={14} /> Scan Locations
        </h2>
        {loading ? (
          <p className="text-sm text-gray-600">Loading…</p>
        ) : roots.length === 0 ? (
          <div className="bg-amber-950/40 border border-amber-800/60 rounded-lg px-4 py-3 text-sm text-amber-300">
            No drives configured yet. Add a folder path above to get started.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {roots.map((r) => {
              const layoutVal = layoutEdits[r.id] ?? r.layout;
              const preview = layoutPreview(layoutVal);
              return (
                <div key={r.id} className="flex flex-col gap-2 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
                  <div className="flex items-center gap-3">
                    <HardDrive size={15} className="text-indigo-400 shrink-0" />
                    <span className="text-sm text-gray-200 flex-1 truncate font-mono">{r.path}</span>
                    {r.last_scanned && (
                      <span className="text-xs text-gray-600 shrink-0">
                        Last scanned {new Date(r.last_scanned).toLocaleDateString()}
                      </span>
                    )}
                    <button
                      onClick={() => removeRoot(r.id, r.path)}
                      className="text-gray-600 hover:text-red-400 transition-colors shrink-0"
                      title="Remove this drive"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  <div className="flex items-center gap-2 pl-[27px]">
                    <label className="text-xs text-gray-500 shrink-0">Layout</label>
                    <input
                      type="text"
                      value={layoutVal}
                      onChange={(e) => setLayoutEdits((m) => ({ ...m, [r.id]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                      onBlur={() => saveLayout(r)}
                      spellCheck={false}
                      className="w-56 bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-xs text-white focus:outline-none font-mono"
                    />
                    <span className={`text-xs truncate ${preview ? "text-gray-600" : "text-amber-400"}`}>
                      {preview ?? "needs exactly one {creator}, last"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 pl-[27px]">
                    <label className="text-xs text-gray-500 shrink-0">Library</label>
                    <input
                      type="text"
                      value={nameEdits[r.id] ?? r.name ?? ""}
                      onChange={(e) => setNameEdits((m) => ({ ...m, [r.id]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                      onBlur={() => saveName(r)}
                      placeholder={r.path.split(/[\\/]/).filter(Boolean).pop() || "name"}
                      spellCheck={false}
                      className="w-40 bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-xs text-white focus:outline-none"
                    />
                    <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer select-none ml-2">
                      <input
                        type="checkbox"
                        checked={r.is_writable}
                        onChange={() => toggleWritable(r)}
                        className="accent-indigo-500"
                      />
                      Import destination
                    </label>
                    <label
                      className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer select-none ml-2"
                      title="Treat every model inside a character folder as one variant group, instead of guessing groups from names. Rescan to apply."
                    >
                      <input
                        type="checkbox"
                        checked={r.group_by_character}
                        onChange={() => toggleGroupByCharacter(r)}
                        className="accent-indigo-500"
                      />
                      Group variants by character
                    </label>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={reloadEnv}
            disabled={reloadingEnv}
            title="Re-read scan roots and drive mappings from the .env file"
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-sm disabled:opacity-50 transition-colors"
          >
            <RefreshCw size={14} className={reloadingEnv ? "animate-spin" : ""} />
            Reload .env settings
          </button>
          <span className="text-xs text-gray-600">
            Applies changes to scan roots and drive paths. Database location still needs a restart.
          </span>
        </div>
      </section>

      {/* Library tools */}
      <section className="pt-6 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <FolderTree size={14} /> Library Tools
        </h2>
        <Link
          to="/reorganize"
          className="flex items-center gap-2 text-sm text-gray-300 hover:text-indigo-300 bg-gray-900 border border-gray-800 hover:border-indigo-700 rounded-lg px-4 py-3 self-start transition-colors w-fit"
        >
          <FolderTree size={15} className="text-indigo-400" />
          Reorganize Library
          <span className="text-xs text-gray-600">— preview a tidy layout, resolve flags, then apply</span>
        </Link>

        <div className="bg-gray-900/60 border border-gray-800 rounded-lg px-4 py-3 mt-4 flex flex-col gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Destination template</label>
            <input
              type="text"
              value={templateEdit ?? settings.reorganize_template}
              onChange={(e) => setTemplateEdit(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              onBlur={saveReorganizeTemplate}
              placeholder="{creator}/{character}/{title}"
              spellCheck={false}
              className="w-72 bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none font-mono"
            />
            <p className="text-xs text-gray-600 mt-1">
              Used by Reorganize Library, new creator folders, and the "unorganized" flag on a model's page.
            </p>
          </div>
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.reorganize_slugify}
              onChange={() => update({ reorganize_slugify: !settings.reorganize_slugify })}
              className="mt-0.5 accent-indigo-500"
            />
            <div>
              <p className="text-sm text-gray-300">Lowercase, hyphenated directory names</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Renders every segment slug-style (e.g. <code className="text-gray-400">abe-3d</code> instead
                of <code className="text-gray-400">Abe 3D</code>), matching how imported folders are named.
                Off keeps the original casing and spacing.
              </p>
            </div>
          </label>
        </div>
      </section>

      {picking && (
        <FolderPicker
          onClose={() => setPicking(false)}
          onSelect={(path) => { setPicking(false); addRoot(path); }}
        />
      )}
    </div>
  );
}
