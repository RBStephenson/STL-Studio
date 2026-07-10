import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { FolderOpen, Play, Check, AlertCircle, Loader2, Inbox, Package } from "lucide-react";
import { api } from "../api/client";
import FolderPicker from "../components/FolderPicker";

type Phase = "idle" | "picking" | "running" | "done" | "error";

export default function ImportPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [selectedPath, setSelectedPath] = useState<string>("/import");
  const [statusMsg, setStatusMsg] = useState<string>("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => () => stopPolling(), []);

  const startImport = async () => {
    if (!selectedPath) return;
    setPhase("running");
    setStatusMsg("starting…");
    try {
      await api.scan.startInboxScan(selectedPath);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "failed to start";
      setPhase("error");
      setStatusMsg(msg);
      return;
    }

    pollRef.current = setInterval(async () => {
      try {
        const s = await api.scan.status();
        setStatusMsg(s.message ?? "");
        if (!s.running) {
          stopPolling();
          if (s.message?.startsWith("error:")) {
            setPhase("error");
          } else {
            setPhase("done");
          }
        }
      } catch {
        // transient; keep polling
      }
    }, 1500);
  };

  const reset = () => {
    stopPolling();
    setPhase("idle");
    setSelectedPath("/import");
    setStatusMsg("");
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-10 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Inbox size={22} className="text-indigo-400" />
          Import Folder
        </h1>
        <p className="mt-2 text-sm text-text-secondary">
          Index an inbox folder without adding it as a permanent scan root.
          Models are imported with an inbox flag so you can enrich and reorganize
          them separately.
        </p>
      </div>

      {/* Step 1 — pick folder */}
      <section className="bg-panel border border-border-subtle rounded-xl p-6 space-y-4">
        <h2 className="font-semibold text-text-primary-alt text-sm uppercase tracking-wide">
          1 — Choose a folder
        </h2>
        <div className="flex items-center gap-3">
          <span className="flex-1 font-mono text-sm text-text-primary-alt2 truncate min-w-0 bg-panel-secondary border border-border rounded px-3 py-2">
            {selectedPath || <span className="text-text-muted">No folder selected</span>}
          </span>
          <button
            onClick={() => setPhase("picking")}
            disabled={phase === "running"}
            className="flex items-center gap-1.5 px-4 py-2 rounded bg-panel-secondary border border-border text-sm text-text-primary-alt2 hover:bg-panel-secondary hover:text-white disabled:opacity-40 transition-colors shrink-0"
          >
            <FolderOpen size={14} />
            Browse
          </button>
        </div>
      </section>

      {/* Step 2 — import */}
      <section className="bg-panel border border-border-subtle rounded-xl p-6 space-y-4">
        <h2 className="font-semibold text-text-primary-alt text-sm uppercase tracking-wide">
          2 — Import
        </h2>

        {phase === "idle" && (
          <div className="flex flex-col gap-3">
            <Link
              to={selectedPath ? `/import/preview?source=${encodeURIComponent(selectedPath)}` : "#"}
              aria-disabled={!selectedPath}
              onClick={(e) => { if (!selectedPath) e.preventDefault(); }}
              className={`flex items-center gap-2 px-5 py-3 rounded-lg text-sm font-medium transition-colors ${
                selectedPath
                  ? "bg-accent-end hover:bg-accent-start text-white"
                  : "bg-accent-end/40 text-white/60 cursor-not-allowed pointer-events-none"
              }`}
            >
              <Package size={14} />
              <span>
                Preview &amp; import packs
                <span className="ml-2 font-normal text-indigo-200 text-xs">Add metadata, fetch from Cults3D / Gumroad / MMF</span>
              </span>
            </Link>
            <button
              onClick={startImport}
              disabled={!selectedPath}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-panel-secondary hover:bg-panel-secondary border border-border text-text-secondary text-xs disabled:opacity-40 transition-colors"
            >
              <Play size={12} />
              Quick import (no metadata)
            </button>
          </div>
        )}

        {phase === "running" && (
          <div className="flex items-center gap-2 text-sm text-text-secondary">
            <Loader2 size={16} className="animate-spin text-indigo-400" />
            <span>{statusMsg || "importing…"}</span>
          </div>
        )}

        {phase === "done" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-green-400">
              <Check size={16} />
              <span>{statusMsg || "done"}</span>
            </div>
            <div className="flex items-center gap-3">
              <Link
                to="/?is_inbox=1"
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent-end hover:bg-accent-start text-white text-sm font-medium transition-colors"
              >
                <Inbox size={14} />
                View inbox models
              </Link>
              <button
                onClick={reset}
                className="px-4 py-2 rounded-lg bg-panel-secondary hover:bg-panel-secondary text-text-primary-alt2 text-sm transition-colors"
              >
                Import another
              </button>
            </div>
          </div>
        )}

        {phase === "error" && (
          <div className="space-y-4">
            <div className="flex items-start gap-2 text-sm text-red-400">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <span>{statusMsg}</span>
            </div>
            <button
              onClick={reset}
              className="px-4 py-2 rounded-lg bg-panel-secondary hover:bg-panel-secondary text-text-primary-alt2 text-sm transition-colors"
            >
              Try again
            </button>
          </div>
        )}
      </section>

      {phase === "picking" && (
        <FolderPicker
          mode="inbox"
          initialPath="/import"
          onSelect={(path) => {
            setSelectedPath(path);
            setPhase("idle");
          }}
          onClose={() => setPhase("idle")}
        />
      )}
    </div>
  );
}
