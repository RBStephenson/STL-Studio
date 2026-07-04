import { useRef, useState } from "react";
import { Database, Download, Upload, Trash2, ShieldAlert, AlertCircle } from "lucide-react";
import { api } from "../../api/client";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";
import { errMsg } from "../../utils/err";

const ACK_PHRASE = "ACKNOWLEDGED";

export default function DataTab() {
  const { success, error, flash } = useSettingsFlash();
  const [busy, setBusy] = useState<null | "backup" | "restore" | "reset">(null);
  const [danger, setDanger] = useState<null | "restore" | "reset">(null);
  const [ack, setAck] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [dangerError, setDangerError] = useState<string | null>(null);
  const restoreInputRef = useRef<HTMLInputElement>(null);

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
    e.target.value = "";
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
      } catch (e) {
        setDangerError(errMsg(e) || "Restore failed");
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
      } catch (e) {
        setDangerError(errMsg(e) || "Delete failed");
      } finally {
        setBusy(null);
      }
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />

      <section>
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
