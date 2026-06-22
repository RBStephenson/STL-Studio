import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import {
  HardDrive, Plus, Trash2, AlertCircle, CheckCircle, FolderSearch,
  Database, Download, Upload, ShieldAlert, Paintbrush, SlidersHorizontal, RefreshCw,
  FolderTree,
} from "lucide-react";
import { api, GuideTheme, ScanRoot } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import FolderPicker from "../components/FolderPicker";
import HelpLink from "../components/HelpLink";
import ThemeEditor from "../components/guide/ThemeEditor";

const ACK_PHRASE = "ACKNOWLEDGED";

// Sample folder name shown for each layout role in the live preview.
const LAYOUT_SAMPLES: Record<string, string> = {
  "{creator}": "Abe3D",
  "{tag}": "Sci-Fi",
  "{ignore}": "_misc",
  "*": "_misc",
};

/**
 * Render a human-readable preview of how a layout template maps folder levels,
 * e.g. "{tag}/{creator}" → "Sci-Fi (tag) › Abe3D (creator) › …models". Returns
 * null when the template breaks a rule the server enforces, so the preview never
 * looks valid for something the backend will reject: every level must be a known
 * token, and there must be exactly one {creator} as the last level.
 */
function layoutPreview(template: string): string | null {
  const segs = (template.trim() || "{creator}")
    .replace(/^[/\\]+|[/\\]+$/g, "")
    .split(/[/\\]+/)
    .filter(Boolean);
  if (segs.length === 0) return null;
  // Exactly one creator, and it must be the last level.
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

export default function Settings() {
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [newPath, setNewPath] = useState("");
  const [newLayout, setNewLayout] = useState("{creator}");
  // Per-root in-progress layout edits, keyed by root id.
  const [layoutEdits, setLayoutEdits] = useState<Record<number, string>>({});
  // Per-root in-progress library-name edits, keyed by root id (#452).
  const [nameEdits, setNameEdits] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { settings: appSettings, update: updateAppSettings } = useAppSettings();

  // Data management
  const [busy, setBusy] = useState<null | "backup" | "restore" | "reset">(null);
  const [danger, setDanger] = useState<null | "restore" | "reset">(null);
  const [ack, setAck] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [dangerError, setDangerError] = useState<string | null>(null);
  const restoreInputRef = useRef<HTMLInputElement>(null);

  const flash = (msg: string, type: "ok" | "err") => {
    if (type === "ok") { setSuccess(msg); setTimeout(() => setSuccess(null), 3000); }
    else { setError(msg); setTimeout(() => setError(null), 4000); }
  };

  const [reloadingEnv, setReloadingEnv] = useState(false);

  // Scan rules — ignore patterns + tag-inference rules (#31)
  const [newPattern, setNewPattern] = useState("");
  const [newKeyword, setNewKeyword] = useState("");
  const [newTag, setNewTag] = useState("");
  const [newPartsName, setNewPartsName] = useState("");

  const load = () => {
    api.scan.roots()
      .then(setRoots)
      .catch(() => flash("Could not load drive list", "err"))
      .finally(() => setLoading(false));
  };

  const reloadEnv = async () => {
    setReloadingEnv(true);
    try {
      const res = await api.settings.reloadEnv();
      load();
      const restart = res.restart_required.length
        ? ` (${res.restart_required.join(", ")} still need a restart)`
        : "";
      flash(`Settings reloaded — ${res.scan_roots.length} scan root(s) from .env${restart}`, "ok");
    } catch (e: any) {
      flash(e?.message || "Could not reload settings", "err");
    } finally {
      setReloadingEnv(false);
    }
  };

  useEffect(() => { load(); }, []);

  const addRoot = async (pathArg?: string) => {
    const path = (pathArg ?? newPath).trim();
    if (!path) return;
    try {
      await api.scan.addRoot(path, newLayout.trim() || "{creator}");
      setNewPath("");
      setNewLayout("{creator}");
      load();
      flash("Drive added — run a scan to index it", "ok");
    } catch (e: any) {
      // request() throws the backend's detail string ("Root already exists",
      // "Path does not exist", layout validation errors) — show it (#216).
      flash(e?.message || "Could not add drive", "err");
    }
  };

  const saveLayout = async (root: ScanRoot) => {
    const next = (layoutEdits[root.id] ?? root.layout).trim() || "{creator}";
    const clearEdit = () =>
      setLayoutEdits((m) => {
        const copy = { ...m };
        delete copy[root.id];
        return copy;
      });
    if (next === root.layout) {
      clearEdit();
      return;
    }
    try {
      await api.scan.updateRoot(root.id, { layout: next });
      clearEdit();
      load();
      flash("Layout updated — rescan to apply it", "ok");
    } catch (e: any) {
      flash(e?.message || "Invalid layout template — check the format", "err");
    }
  };

  const saveName = async (root: ScanRoot) => {
    const next = (nameEdits[root.id] ?? root.name ?? "").trim();
    const clearEdit = () =>
      setNameEdits((m) => {
        const copy = { ...m };
        delete copy[root.id];
        return copy;
      });
    if (next === (root.name ?? "")) {
      clearEdit();
      return;
    }
    try {
      await api.scan.updateRoot(root.id, { name: next });
      clearEdit();
      load();
      flash("Library name updated", "ok");
    } catch (e: any) {
      flash(e?.message || "Couldn't update the library name", "err");
    }
  };

  const toggleWritable = async (root: ScanRoot) => {
    try {
      await api.scan.updateRoot(root.id, { is_writable: !root.is_writable });
      load();
      flash(root.is_writable ? "No longer an import destination" : "Marked as an import destination", "ok");
    } catch (e: any) {
      flash(e?.message || "Couldn't update the library", "err");
    }
  };

  const removeRoot = async (id: number, path: string) => {
    if (!confirm(`Remove "${path}" from the library?\n\nThis won't delete any files — just removes it from scanning.`)) return;
    try {
      await api.scan.removeRoot(id);
      load();
      flash("Drive removed", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not remove drive", "err");
    }
  };

  const backup = async () => {
    setBusy("backup");
    try {
      await api.database.backup();
      flash("Backup downloaded", "ok");
    } catch {
      flash("Backup failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const openRestore = () => {
    setRestoreFile(null);
    restoreInputRef.current?.click();
  };

  const onRestoreFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file later
    if (!f) return;
    setRestoreFile(f);
    setAck("");
    setDanger("restore");
  };

  const closeDanger = () => { setDanger(null); setAck(""); setRestoreFile(null); setDangerError(null); };

  const confirmDanger = async () => {
    if (ack.trim().toUpperCase() !== ACK_PHRASE) return;
    if (danger === "restore" && restoreFile) {
      setBusy("restore");
      setDangerError(null);
      try {
        await api.database.restore(restoreFile);
        closeDanger();
        flash("Database restored — reloading…", "ok");
        setTimeout(() => window.location.reload(), 1200);
      } catch (e: any) {
        setDangerError(e.message || "Restore failed");
      } finally {
        setBusy(null);
      }
    } else if (danger === "reset") {
      setBusy("reset");
      setDangerError(null);
      try {
        await api.database.reset();
        closeDanger();
        flash("All data deleted — reloading…", "ok");
        setTimeout(() => window.location.reload(), 1200);
      } catch (e: any) {
        setDangerError(e.message || "Delete failed");
      } finally {
        setBusy(null);
      }
    }
  };

  const setPageSize = async (n: number) => {
    try {
      await updateAppSettings({ library_page_size: n });
    } catch (e: any) {
      flash(e?.message || "Could not update setting", "err");
    }
  };

  const setRecentDays = async (n: number) => {
    try {
      await updateAppSettings({ recent_days: n });
    } catch (e: any) {
      flash(e?.message || "Could not update setting", "err");
    }
  };

  const togglePaintingGuides = async () => {
    const next = !appSettings.painting_guides_enabled;
    try {
      await updateAppSettings({ painting_guides_enabled: next });
      flash(next ? "Painting Guides enabled" : "Painting Guides disabled", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not update setting", "err");
    }
  };

  const saveThemeDefaults = async (theme: GuideTheme) => {
    try {
      await updateAppSettings({ guide_theme_defaults: theme });
    } catch (e: any) {
      flash(e?.message || "Could not save theme defaults", "err");
    }
  };

  const addIgnorePattern = async () => {
    const pat = newPattern.trim();
    if (!pat) return;
    const current = appSettings.scan_ignore_patterns;
    if (current.includes(pat)) {
      setNewPattern("");
      return;
    }
    try {
      await updateAppSettings({ scan_ignore_patterns: [...current, pat] });
      setNewPattern("");
    } catch (e: any) {
      flash(e?.message || "Could not add ignore pattern", "err");
    }
  };

  const removeIgnorePattern = async (pat: string) => {
    try {
      await updateAppSettings({
        scan_ignore_patterns: appSettings.scan_ignore_patterns.filter((p) => p !== pat),
      });
    } catch (e: any) {
      flash(e?.message || "Could not remove ignore pattern", "err");
    }
  };

  const addTagRule = async () => {
    const keyword = newKeyword.trim();
    const tag = newTag.trim();
    if (!keyword || !tag) return;
    const current = appSettings.scan_tag_rules;
    if (current.some((r) => r.keyword.toLowerCase() === keyword.toLowerCase()
                         && r.tag.toLowerCase() === tag.toLowerCase())) {
      setNewKeyword(""); setNewTag("");
      return;
    }
    try {
      await updateAppSettings({ scan_tag_rules: [...current, { keyword, tag }] });
      setNewKeyword(""); setNewTag("");
    } catch (e: any) {
      flash(e?.message || "Could not add tag rule", "err");
    }
  };

  const removeTagRule = async (keyword: string, tag: string) => {
    try {
      await updateAppSettings({
        scan_tag_rules: appSettings.scan_tag_rules.filter(
          (r) => !(r.keyword === keyword && r.tag === tag)
        ),
      });
    } catch (e: any) {
      flash(e?.message || "Could not remove tag rule", "err");
    }
  };

  const addPartsName = async () => {
    const name = newPartsName.trim();
    if (!name) return;
    const current = appSettings.scan_parts_names;
    if (current.some((n) => n.toLowerCase() === name.toLowerCase())) {
      setNewPartsName("");
      return;
    }
    try {
      await updateAppSettings({ scan_parts_names: [...current, name] });
      setNewPartsName("");
    } catch (e: any) {
      flash(e?.message || "Could not add parts name", "err");
    }
  };

  const removePartsName = async (name: string) => {
    try {
      await updateAppSettings({
        scan_parts_names: appSettings.scan_parts_names.filter((n) => n !== name),
      });
    } catch (e: any) {
      flash(e?.message || "Could not remove parts name", "err");
    }
  };

  const examples: Record<string, string[]> = {
    Windows: ["D:\\3D STLs", "E:\\My Models"],
    macOS: ["/Volumes/MyDrive/3D STLs"],
    Linux: ["/media/username/MyDrive/STLs", "/mnt/nas/models"],
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="flex items-center gap-2 text-2xl font-bold text-white mb-1">
        Settings
        <HelpLink section="settings" label="About scan locations & data management" />
      </h1>
      <p className="text-sm text-gray-500 mb-8">Manage the drives and folders that STL Library scans for models.</p>

      {/* Feedback */}
      {success && (
        <div className="flex items-center gap-2 bg-green-950/60 border border-green-800 text-green-300 text-sm px-4 py-2.5 rounded-lg mb-4">
          <CheckCircle size={15} /> {success}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 bg-red-950/60 border border-red-800 text-red-300 text-sm px-4 py-2.5 rounded-lg mb-4">
          <AlertCircle size={15} /> {error}
        </div>
      )}

      {/* Current roots */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <HardDrive size={14} /> Scan Locations
        </h2>

        {loading ? (
          <p className="text-sm text-gray-600">Loading…</p>
        ) : roots.length === 0 ? (
          <div className="bg-amber-950/40 border border-amber-800/60 rounded-lg px-4 py-3 text-sm text-amber-300">
            No drives configured yet. Add a folder path below to get started.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {roots.map((r) => {
              const layoutVal = layoutEdits[r.id] ?? r.layout;
              const preview = layoutPreview(layoutVal);
              return (
                <div
                  key={r.id}
                  className="flex flex-col gap-2 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3"
                >
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
                  {/* Library name + import-destination toggle (#452) */}
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
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Re-read scan roots / drive mappings from .env without a restart (#140) */}
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

        {/* How layouts work — example shown above the folder-layout input */}
        <div className="bg-gray-900/60 border border-gray-800 rounded-lg px-4 py-3 mt-4">
          <p className="text-xs text-gray-400 mb-2">
            A <strong className="text-gray-300">layout</strong> tells STL Library how the folders
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
            Tokens you can use: <code className="text-gray-400">{"{creator}"}</code> (required, last
            level), <code className="text-gray-400">{"{tag}"}</code> (tag every model with the folder
            name), and <code className="text-gray-400">{"{ignore}"}</code> (skip a level).
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
          <p className="text-xs text-gray-600 mt-2 leading-relaxed">
            Describe the folders <em>above your models</em>, one level per <code className="text-gray-500">/</code>.
            Use <code className="text-gray-500">{"{creator}"}</code> for the creator level (required, last),
            <code className="text-gray-500"> {"{tag}"}</code> to tag every model with a folder name
            (e.g. genre), and <code className="text-gray-500">{"{ignore}"}</code> to skip a level.
            The default <code className="text-gray-500">{"{creator}"}</code> means the top folders are creators.
          </p>
        </div>
      </section>

      {/* Path examples */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Path Examples
        </h2>
        <div className="flex flex-col gap-3">
          {Object.entries(examples).map(([os, paths]) => (
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

      {/* Library tools */}
      <section className="mt-12 pt-8 border-t border-gray-800">
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
      </section>

      {/* Preferences */}
      <section className="mt-12 pt-8 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <SlidersHorizontal size={14} /> Preferences
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Preferences are stored server-side, so they follow you across browsers and devices.
          The NSFW toggle in the navbar and your saved Library filter presets are persisted the same way.
        </p>
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 self-start">
            <span className="text-sm text-gray-200">Library page size</span>
            <div className="flex rounded overflow-hidden border border-gray-700">
              {[24, 48, 96].map((n) => (
                <button
                  key={n}
                  onClick={() => setPageSize(n)}
                  className={`px-3 py-1 text-xs transition-colors ${
                    appSettings.library_page_size === n
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-800 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 self-start">
            <span className="text-sm text-gray-200">"New" badge window</span>
            <div className="flex rounded overflow-hidden border border-gray-700">
              {[3, 7, 14, 30].map((n) => (
                <button
                  key={n}
                  onClick={() => setRecentDays(n)}
                  className={`px-3 py-1 text-xs transition-colors ${
                    appSettings.recent_days === n
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-800 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {n}d
                </button>
              ))}
            </div>
            <span className="text-xs text-gray-600">drives the Library's "recently added" filter too</span>
          </div>
        </div>
      </section>

      {/* Scan Rules — ignore patterns (#31) */}
      <section className="mt-12 pt-8 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <FolderSearch size={14} /> Scan Rules
          <HelpLink section="scan-rules" label="About scan rules" />
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Folders matching an <strong className="text-gray-500">ignore pattern</strong> (and everything
          inside them) are skipped during scanning. Matching is case-insensitive against a folder's name
          (e.g. <code className="text-gray-500">WIP</code>) or its full path (e.g.{" "}
          <code className="text-gray-500">*/_archive/*</code>). Patterns take effect on the next scan;
          any already-indexed models they now cover are removed.
        </p>
        <div className="flex flex-col gap-2 self-start" data-testid="ignore-patterns">
          {appSettings.scan_ignore_patterns.length === 0 && (
            <p className="text-xs text-gray-600 italic">No ignore patterns yet.</p>
          )}
          {appSettings.scan_ignore_patterns.map((pat) => (
            <div
              key={pat}
              className="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 self-start min-w-[18rem]"
            >
              <code className="text-sm text-gray-200">{pat}</code>
              <button
                onClick={() => removeIgnorePattern(pat)}
                aria-label={`Remove ${pat}`}
                className="text-gray-500 hover:text-red-400 transition-colors"
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
              className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-64"
            />
            <button
              onClick={addIgnorePattern}
              disabled={!newPattern.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Plus size={14} /> Add
            </button>
          </div>
        </div>

        <p className="text-xs text-gray-600 mt-6 mb-4">
          <strong className="text-gray-500">Tag rules</strong> add an auto-tag to any model whose
          name contains a keyword — e.g. keyword <code className="text-gray-500">Aztec</code> →
          tag <code className="text-gray-500">civ</code>. These add to the built-in tag detection and
          apply on the next full scan; they don't affect how variants group.
        </p>
        <div className="flex flex-col gap-2 self-start" data-testid="tag-rules">
          {appSettings.scan_tag_rules.length === 0 && (
            <p className="text-xs text-gray-600 italic">No tag rules yet.</p>
          )}
          {appSettings.scan_tag_rules.map((r) => (
            <div
              key={`${r.keyword} ${r.tag}`}
              className="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 self-start min-w-[18rem]"
            >
              <span className="text-sm text-gray-200">
                <code>{r.keyword}</code>
                <span className="text-gray-600 mx-2">&rarr;</span>
                <code className="text-indigo-300">{r.tag}</code>
              </span>
              <button
                onClick={() => removeTagRule(r.keyword, r.tag)}
                aria-label={`Remove ${r.keyword} to ${r.tag}`}
                className="text-gray-500 hover:text-red-400 transition-colors"
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
              className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-44"
            />
            <span className="text-gray-600">&rarr;</span>
            <input
              type="text"
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTagRule(); } }}
              placeholder="tag (e.g. civ)"
              className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-44"
            />
            <button
              onClick={addTagRule}
              disabled={!newKeyword.trim() || !newTag.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Plus size={14} /> Add
            </button>
          </div>
        </div>

        <p className="text-xs text-gray-600 mt-6 mb-4">
          <strong className="text-gray-500">Parts folder names</strong> are exact folder names
          treated as parts/structure (e.g. <code className="text-gray-500">Sprues</code>,{" "}
          <code className="text-gray-500">Magnets</code>) — never indexed as their own model and
          never used to group variants. These add to the built-in names (Parts, Base, Supports…)
          and apply on the next full scan.
        </p>
        <div className="flex flex-col gap-2 self-start" data-testid="parts-names">
          {appSettings.scan_parts_names.length === 0 && (
            <p className="text-xs text-gray-600 italic">No custom parts names yet.</p>
          )}
          {appSettings.scan_parts_names.map((name) => (
            <div
              key={name}
              className="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 self-start min-w-[18rem]"
            >
              <code className="text-sm text-gray-200">{name}</code>
              <button
                onClick={() => removePartsName(name)}
                aria-label={`Remove ${name}`}
                className="text-gray-500 hover:text-red-400 transition-colors"
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
              className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-64"
            />
            <button
              onClick={addPartsName}
              disabled={!newPartsName.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Plus size={14} /> Add
            </button>
          </div>
        </div>
      </section>

      {/* Painting Guides */}
      <section className="mt-12 pt-8 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Paintbrush size={14} /> Painting Guides
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Author step-by-step painting guides for your models. Enabling this adds{" "}
          <strong className="text-gray-500">Guides</strong> to the navigation. The{" "}
          <strong className="text-gray-500">Paint Shelf</strong> is always available.
        </p>
        <label className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 cursor-pointer select-none self-start">
          <input
            type="checkbox"
            checked={appSettings.painting_guides_enabled}
            onChange={togglePaintingGuides}
            className="h-4 w-4 accent-indigo-500"
          />
          <span className="text-sm text-gray-200">Enable Painting Guides</span>
        </label>

        {appSettings.painting_guides_enabled && (
          <div className="mt-6">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Default guide theme
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              New guides inherit these colors. Each guide can override them in its editor.
            </p>
            <ThemeEditor
              value={appSettings.guide_theme_defaults}
              onChange={saveThemeDefaults}
            />
          </div>
        )}
      </section>

      {/* Data management */}
      <section className="mt-12 pt-8 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Database size={14} /> Data Management
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Back up your library to a file, restore from a previous backup, or wipe the database entirely.
          Your STL files on disk are never touched — only the index of metadata, tags, and queue state.
        </p>

        <div className="flex flex-col gap-2">
          <button
            onClick={backup}
            disabled={busy !== null}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed self-start"
          >
            <Download size={15} />
            {busy === "backup" ? "Preparing backup…" : "Download Backup"}
          </button>

          {/* Danger zone */}
          <div className="mt-4 rounded-lg border border-red-900/70 bg-red-950/20 p-4">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-red-400 mb-1">
              <ShieldAlert size={14} /> Danger Zone
            </p>
            <p className="text-xs text-red-300/70 mb-4">
              These actions permanently overwrite or erase your library index and cannot be undone.
              Download a backup first.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={openRestore}
                disabled={busy !== null}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-950/60 hover:bg-red-900/60 border border-red-800 text-red-200 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Upload size={15} /> Restore from Backup…
              </button>
              <button
                onClick={() => { setAck(""); setRestoreFile(null); setDanger("reset"); }}
                disabled={busy !== null}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 border border-red-600 text-white text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Trash2 size={15} /> Delete All Data
              </button>
            </div>
            <input
              ref={restoreInputRef}
              type="file"
              accept=".db,.sqlite,.sqlite3,application/octet-stream"
              onChange={onRestoreFile}
              className="hidden"
            />
          </div>
        </div>
      </section>

      {picking && (
        <FolderPicker
          onClose={() => setPicking(false)}
          onSelect={(path) => { setPicking(false); addRoot(path); }}
        />
      )}

      {danger && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
          <div className="w-full max-w-md rounded-xl border border-red-800 bg-gray-900 p-6 shadow-2xl">
            <h3 className="flex items-center gap-2 text-lg font-bold text-red-300 mb-2">
              <ShieldAlert size={20} />
              {danger === "restore" ? "Restore database?" : "Delete all data?"}
            </h3>

            {danger === "restore" ? (
              <p className="text-sm text-gray-300 mb-4">
                This will <strong className="text-red-300">overwrite your entire current library</strong> with
                the contents of{" "}
                <span className="font-mono text-gray-200">{restoreFile?.name}</span>. Everything currently
                indexed — metadata, tags, favorites, and print queue — will be replaced and{" "}
                <strong className="text-red-300">cannot be recovered</strong> unless you have a backup.
              </p>
            ) : (
              <p className="text-sm text-gray-300 mb-4">
                This will <strong className="text-red-300">permanently erase every model, tag, collection,
                favorite, and print-queue entry</strong> from your library index. You'll need to run a full
                rescan to rebuild it. This <strong className="text-red-300">cannot be undone</strong>.
              </p>
            )}

            <label className="block text-xs text-gray-400 mb-1.5">
              Type <span className="font-mono font-semibold text-red-300">{ACK_PHRASE}</span> to confirm:
            </label>
            <input
              autoFocus
              value={ack}
              onChange={(e) => setAck(e.target.value)}
              placeholder={ACK_PHRASE}
              className="w-full bg-gray-950 border border-gray-700 focus:border-red-500 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-700 focus:outline-none font-mono tracking-wider mb-4"
            />

            {dangerError && (
              <div className="flex items-center gap-2 bg-red-950/60 border border-red-800 text-red-300 text-sm px-3 py-2 rounded-lg mb-4">
                <AlertCircle size={14} className="shrink-0" /> {dangerError}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={closeDanger}
                disabled={busy !== null}
                className="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={confirmDanger}
                disabled={busy !== null || ack.trim().toUpperCase() !== ACK_PHRASE}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy === "restore" ? "Restoring…" : busy === "reset" ? "Deleting…"
                  : danger === "restore" ? "Overwrite Library" : "Delete Everything"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
