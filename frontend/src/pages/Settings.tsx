import { useEffect, useState, useRef } from "react";
import {
  HardDrive, Plus, Trash2, AlertCircle, CheckCircle, FolderSearch,
  Database, Download, Upload, ShieldAlert,
} from "lucide-react";
import { api, ScanRoot } from "../api/client";
import FolderPicker from "../components/FolderPicker";

const ACK_PHRASE = "ACKNOWLEDGED";

export default function Settings() {
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [newPath, setNewPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Data management
  const [busy, setBusy] = useState<null | "backup" | "restore" | "reset">(null);
  const [danger, setDanger] = useState<null | "restore" | "reset">(null);
  const [ack, setAck] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const restoreInputRef = useRef<HTMLInputElement>(null);

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

  const closeDanger = () => { setDanger(null); setAck(""); setRestoreFile(null); };

  const confirmDanger = async () => {
    if (ack.trim().toUpperCase() !== ACK_PHRASE) return;
    if (danger === "restore" && restoreFile) {
      setBusy("restore");
      try {
        await api.database.restore(restoreFile);
        closeDanger();
        flash("Database restored — reloading…", "ok");
        setTimeout(() => window.location.reload(), 1200);
      } catch (e: any) {
        flash(e.message || "Restore failed", "err");
      } finally {
        setBusy(null);
      }
    } else if (danger === "reset") {
      setBusy("reset");
      try {
        await api.database.reset();
        closeDanger();
        flash("All data deleted — reloading…", "ok");
        setTimeout(() => window.location.reload(), 1200);
      } catch (e: any) {
        flash(e.message || "Delete failed", "err");
      } finally {
        setBusy(null);
      }
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
