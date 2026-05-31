import { useEffect, useState, useRef } from "react";
import { HardDrive, Plus, Trash2, AlertCircle, CheckCircle, FolderSearch } from "lucide-react";
import { api, ScanRoot } from "../api/client";
import FolderPicker from "../components/FolderPicker";

export default function Settings() {
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [newPath, setNewPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const flash = (msg: string, type: "ok" | "err") => {
    if (type === "ok") { setSuccess(msg); setTimeout(() => setSuccess(null), 3000); }
    else { setError(msg); setTimeout(() => setError(null), 4000); }
  };

  const load = () => {
    api.scan.roots()
      .then(setRoots)
      .catch(() => flash("Could not load drive list", "err"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const addRoot = async (pathArg?: string) => {
    const path = (pathArg ?? newPath).trim();
    if (!path) return;
    try {
      await api.scan.addRoot(path);
      setNewPath("");
      load();
      flash("Drive added — run a scan to index it", "ok");
    } catch (e: any) {
      flash(e.message.includes("409") ? "That path is already in the list" : "Could not add drive", "err");
    }
  };

  const removeRoot = async (id: number, path: string) => {
    if (!confirm(`Remove "${path}" from the library?\n\nThis won't delete any files — just removes it from scanning.`)) return;
    try {
      await api.scan.removeRoot(id);
      load();
      flash("Drive removed", "ok");
    } catch {
      flash("Could not remove drive", "err");
    }
  };

  const examples: Record<string, string[]> = {
    Windows: ["D:\\3D STLs", "E:\\My Models"],
    macOS: ["/Volumes/MyDrive/3D STLs"],
    Linux: ["/media/username/MyDrive/STLs", "/mnt/nas/models"],
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-white mb-1">Settings</h1>
      <p className="text-sm text-gray-500 mb-8">Manage the drives and folders that STL Inventory scans for models.</p>

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
            {roots.map((r) => (
              <div
                key={r.id}
                className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3"
              >
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
            ))}
          </div>
        )}
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
            onClick={() => addRoot()}
            disabled={!newPath.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm transition-colors"
          >
            <Plus size={15} />
            Add
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          Use <strong className="text-gray-500">Browse…</strong> to pick a folder, or type the full path. Subfolders are scanned automatically.
        </p>
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

      {picking && (
        <FolderPicker
          onClose={() => setPicking(false)}
          onSelect={(path) => { setPicking(false); addRoot(path); }}
        />
      )}
    </div>
  );
}
