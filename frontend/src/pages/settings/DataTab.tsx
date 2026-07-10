import { useRef, useState } from "react";
import { AlertCircle, Database, Download, LoaderCircle, ShieldAlert, ShieldCheck, Trash2, Upload, Wrench } from "lucide-react";
import { api } from "../../api/client";
import type { DatabaseHealth } from "../../api/database";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";
import { errMsg } from "../../utils/err";

const ACK_PHRASE = "ACKNOWLEDGED";

export default function DataTab() {
  const { success, error, flash } = useSettingsFlash();
  const [busy, setBusy] = useState<null | "backup" | "health" | "repair" | "restore" | "reset">(null);
  const [danger, setDanger] = useState<null | "repair" | "restore" | "reset">(null);
  const [ack, setAck] = useState("");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [dangerError, setDangerError] = useState<string | null>(null);
  const [health, setHealth] = useState<DatabaseHealth | null>(null);
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

  const checkHealth = async () => {
    setBusy("health");
    try {
      const result = await api.database.health();
      setHealth(result);
      flash(result.ok ? "Database health check passed" : "Database corruption detected", result.ok ? "ok" : "err");
    } catch (e) {
      flash(errMsg(e) || "Health check failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const openRepair = () => {
    setAck("");
    setRestoreFile(null);
    setDanger("repair");
  };

  const closeDanger = () => { setDanger(null); setAck(""); setRestoreFile(null); setDangerError(null); };

  const confirmDanger = async () => {
    if (ack.trim().toUpperCase() !== ACK_PHRASE) return;
    if (danger === "repair") {
      setBusy("repair");
      setDangerError(null);
      try {
        const result = await api.database.repair();
        setHealth({ ok: result.ok, status: result.status, detail: result.detail });
        closeDanger();
        flash(
          result.repaired ? "Database repaired" : result.ok ? "Database is already healthy" : "Database repair did not fully resolve corruption",
          result.ok ? "ok" : "err",
        );
      } catch (e) {
        setDangerError(errMsg(e) || "Repair failed");
      } finally {
        setBusy(null);
      }
    } else if (danger === "restore" && restoreFile) {
      setBusy("restore");
      setDangerError(null);
      try {
        const result = await api.database.restore(restoreFile);
        closeDanger();
        if (result.warning) {
          flash(`Database restored; ${result.warning} Reloading...`, "ok");
          setTimeout(() => window.location.reload(), 1200);
          return;
        }
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
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Database size={14} /> Data Management
        </h2>
        <p className="text-xs text-text-muted mb-4">
          Back up your library to a file, restore from a previous backup, or wipe the database entirely.
          Your STL files on disk are never touched — only the index of metadata, tags, and queue state.
        </p>

        <div className="flex flex-col gap-2">
          <button
            onClick={backup}
            disabled={busy !== null}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-panel-secondary hover:bg-panel-secondary border border-border text-text-primary-alt text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed self-start"
          >
            <Download size={15} />
            {busy === "backup" ? "Preparing backup…" : "Download Backup"}
          </button>

          <div className="mt-2 rounded-lg border border-border-subtle bg-panel-inset/40 p-4">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1">
              <ShieldCheck size={14} /> Database Health
            </p>
            <p className="text-xs text-text-secondary-alt mb-3">
              Run a SQLite integrity check or attempt a safe index repair. Repair snapshots the database first and does not touch STL files.
            </p>
            {busy === "health" ? (
              <div
                role="status"
                aria-live="polite"
                className="mb-3 flex items-center gap-2 rounded-lg border border-sky-900/70 bg-sky-950/20 px-3 py-2 text-xs text-sky-300"
              >
                <LoaderCircle size={14} className="animate-spin shrink-0" />
                <span>
                  <span className="font-semibold">Checking database...</span> This can take a minute on a large library.
                </span>
              </div>
            ) : health && (
              <div
                className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                  health.ok
                    ? "border-emerald-900/70 bg-emerald-950/20 text-emerald-300"
                    : "border-red-900/70 bg-red-950/20 text-red-300"
                }`}
              >
                <span className="font-semibold">{health.ok ? "Healthy" : "Corruption detected"}:</span>{" "}
                <span className="font-mono break-words">{health.detail}</span>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                onClick={checkHealth}
                disabled={busy !== null}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-panel-secondary hover:bg-panel-secondary border border-border text-text-primary-alt text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ShieldCheck size={15} />
                {busy === "health" ? "Checking..." : "Check Health"}
              </button>
              <button
                onClick={openRepair}
                disabled={busy !== null || health?.ok !== false}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-950/50 hover:bg-amber-900/50 border border-amber-800 text-amber-200 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Wrench size={15} />
                {busy === "repair" ? "Repairing..." : "Repair Database"}
              </button>
            </div>
          </div>

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
          <div className="w-full max-w-md rounded-xl border border-red-800 bg-panel p-6 shadow-2xl">
            <h3 className="flex items-center gap-2 text-lg font-bold text-red-300 mb-2">
              <ShieldAlert size={20} />
              {danger === "repair" ? "Repair database?" : danger === "restore" ? "Restore database?" : "Delete all data?"}
            </h3>
            {danger === "repair" ? (
              <p className="text-sm text-text-primary-alt2 mb-4">
                This will snapshot your current database, run SQLite <span className="font-mono text-text-primary-alt">REINDEX</span>,
                and verify the result with an integrity check. It is intended for index corruption only; deeper corruption may
                still require manual recovery from backup.
              </p>
            ) : danger === "restore" ? (
              <p className="text-sm text-text-primary-alt2 mb-4">
                This will <strong className="text-red-300">overwrite your entire current library</strong> with
                the contents of{" "}
                <span className="font-mono text-text-primary-alt">{restoreFile?.name}</span>. Everything currently
                indexed — metadata, tags, favorites, and print queue — will be replaced and{" "}
                <strong className="text-red-300">cannot be recovered</strong> unless you have a backup.
              </p>
            ) : (
              <p className="text-sm text-text-primary-alt2 mb-4">
                This will <strong className="text-red-300">permanently erase every model, tag, collection,
                favorite, and print-queue entry</strong> from your library index. You'll need to run a full
                rescan to rebuild it. This <strong className="text-red-300">cannot be undone</strong>.
              </p>
            )}
            <label className="block text-xs text-text-secondary mb-1.5">
              Type <span className="font-mono font-semibold text-red-300">{ACK_PHRASE}</span> to confirm:
            </label>
            <input
              autoFocus
              value={ack}
              onChange={(e) => setAck(e.target.value)}
              placeholder={ACK_PHRASE}
              className="w-full bg-panel-inset border border-border focus:border-red-500 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-700 focus:outline-none font-mono tracking-wider mb-4"
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
                className="px-4 py-2 rounded-lg bg-panel-secondary hover:bg-panel-secondary text-text-primary-alt text-sm transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={confirmDanger}
                disabled={busy !== null || ack.trim().toUpperCase() !== ACK_PHRASE}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy === "repair" ? "Repairing..." : busy === "restore" ? "Restoring…" : busy === "reset" ? "Deleting…"
                  : danger === "repair" ? "Repair Database" : danger === "restore" ? "Overwrite Library" : "Delete Everything"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
