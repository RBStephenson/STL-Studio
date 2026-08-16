import { useState, useEffect, useRef, useMemo } from "react";
import { FolderOpen, Package, Check, AlertCircle, Loader2, PackagePlus, ScanLine, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Creator, InstallResult, Library } from "../api/types";
import FolderPicker from "../components/FolderPicker";

type Phase = "idle" | "installing" | "installed" | "error";
type ScanPhase = "idle" | "scanning" | "done" | "error";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

export default function InstallPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [picking, setPicking] = useState(false);
  const [sourcePath, setSourcePath] = useState("");

  const [libraries, setLibraries] = useState<Library[]>([]);
  const [libraryId, setLibraryId] = useState<number | "">("");

  const [creators, setCreators] = useState<Creator[]>([]);
  const [creatorId, setCreatorId] = useState<number | "">("");
  const [addingCreator, setAddingCreator] = useState(false);
  const [newCreatorName, setNewCreatorName] = useState("");

  const [character, setCharacter] = useState("");

  const [error, setError] = useState<string>("");
  const [result, setResult] = useState<InstallResult | null>(null);

  const [scanPhase, setScanPhase] = useState<ScanPhase>("idle");
  const [scanMsg, setScanMsg] = useState("");
  const scanPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.scan.libraries().then((libs) => {
      setLibraries(libs);
      const writable = libs.filter((l) => l.is_writable);
      if (writable.length === 1) setLibraryId(writable[0].id);
    }).catch(() => {});
    api.models.creators().then(setCreators).catch(() => {});
  }, []);

  useEffect(() => () => {
    if (scanPollRef.current) clearInterval(scanPollRef.current);
  }, []);

  const writableLibraries = useMemo(() => libraries.filter((l) => l.is_writable), [libraries]);
  const selectedLibrary = useMemo(
    () => libraries.find((l) => l.id === libraryId) ?? null,
    [libraries, libraryId]
  );
  const creatorName = addingCreator
    ? newCreatorName.trim()
    : creators.find((c) => c.id === creatorId)?.name ?? "";

  const destinationPreview = selectedLibrary && creatorName && character.trim()
    ? `${selectedLibrary.path}/${creatorName}/${character.trim()}`
    : null;

  const canInstall = !!sourcePath && !!selectedLibrary && !!creatorName && !!character.trim();

  const install = async () => {
    if (!canInstall || !selectedLibrary) return;
    setPhase("installing");
    setError("");
    try {
      const r = await api.import.install(sourcePath, selectedLibrary.id, creatorName, character.trim());
      setResult(r);
      setPhase("installed");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Install failed");
      setPhase("error");
    }
  };

  const scanNow = () => {
    if (!result) return;
    setScanPhase("scanning");
    setScanMsg("starting…");
    api.scan.startCreator(result.creator_id).catch((e: unknown) => {
      setScanPhase("error");
      setScanMsg(e instanceof Error ? e.message : "failed to start");
    });

    scanPollRef.current = setInterval(async () => {
      try {
        const s = await api.scan.status();
        setScanMsg(s.message ?? "");
        if (!s.running) {
          if (scanPollRef.current) clearInterval(scanPollRef.current);
          scanPollRef.current = null;
          setScanPhase(s.message?.startsWith("error:") ? "error" : "done");
        }
      } catch {
        // transient; keep polling
      }
    }, 1500);
  };

  const reset = () => {
    setPhase("idle");
    setSourcePath("");
    setCreatorId("");
    setAddingCreator(false);
    setNewCreatorName("");
    setCharacter("");
    setError("");
    setResult(null);
    setScanPhase("idle");
    setScanMsg("");
    api.models.creators().then(setCreators).catch(() => {});
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-10 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <PackagePlus size={22} className="text-indigo-400" />
          Install
        </h1>
        <p className="mt-2 text-sm text-text-secondary">
          Extract a ZIP or copy a folder straight into a library as creator/character —
          skips the manual download, extract, move, and scan steps.
        </p>
      </div>

      {/* Step 1 — source */}
      <section className="bg-panel border border-border-subtle rounded-xl p-6 space-y-4">
        <h2 className="font-semibold text-text-primary-alt text-sm uppercase tracking-wide">
          1 — Choose a ZIP or folder
        </h2>
        <div className="flex items-center gap-3">
          <span className="flex-1 font-mono text-sm text-text-primary-alt2 truncate min-w-0 bg-panel-secondary border border-border rounded px-3 py-2">
            {sourcePath || <span className="text-text-muted">No source selected</span>}
          </span>
          <button
            onClick={() => setPicking(true)}
            disabled={phase === "installing"}
            className="flex items-center gap-1.5 px-4 py-2 rounded bg-panel-secondary border border-border text-sm text-text-primary-alt2 hover:bg-panel-secondary hover:text-white disabled:opacity-40 transition-colors shrink-0"
          >
            <FolderOpen size={14} />
            Browse
          </button>
        </div>
      </section>

      {/* Step 2 — destination */}
      <section className="bg-panel border border-border-subtle rounded-xl p-6 space-y-4">
        <h2 className="font-semibold text-text-primary-alt text-sm uppercase tracking-wide">
          2 — Destination
        </h2>

        <div>
          <label htmlFor="install-library" className="block text-xs text-text-secondary-alt mb-1">Library</label>
          <select
            id="install-library"
            value={libraryId}
            onChange={(e) => setLibraryId(e.target.value ? Number(e.target.value) : "")}
            disabled={phase === "installing"}
            className="w-full bg-panel-inset border border-border focus:border-accent-start rounded px-2 py-1.5 text-sm text-white disabled:opacity-40 focus:outline-none"
          >
            <option value="">Select a library…</option>
            {writableLibraries.map((l) => (
              <option key={l.id} value={l.id}>{l.name} ({l.path})</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="install-creator" className="block text-xs text-text-secondary-alt mb-1">Creator</label>
          {addingCreator ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={newCreatorName}
                onChange={(e) => setNewCreatorName(e.target.value)}
                disabled={phase === "installing"}
                placeholder="New creator name"
                className="flex-1 bg-panel-inset border border-border focus:border-accent-start rounded px-2 py-1.5 text-sm text-white placeholder-gray-600 disabled:opacity-40 focus:outline-none"
              />
              <button
                onClick={() => { setAddingCreator(false); setNewCreatorName(""); }}
                disabled={phase === "installing"}
                className="px-3 py-1.5 rounded bg-panel-secondary border border-border text-xs text-text-secondary hover:text-white disabled:opacity-40 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <select
                id="install-creator"
                value={creatorId}
                onChange={(e) => setCreatorId(e.target.value ? Number(e.target.value) : "")}
                disabled={phase === "installing"}
                className="flex-1 bg-panel-inset border border-border focus:border-accent-start rounded px-2 py-1.5 text-sm text-white disabled:opacity-40 focus:outline-none"
              >
                <option value="">Select a creator…</option>
                {creators.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <button
                onClick={() => { setAddingCreator(true); setCreatorId(""); }}
                disabled={phase === "installing"}
                className="flex items-center gap-1 px-3 py-1.5 rounded bg-panel-secondary border border-border text-xs text-text-secondary hover:text-white disabled:opacity-40 transition-colors shrink-0"
              >
                <Plus size={12} />
                New
              </button>
            </div>
          )}
        </div>

        <div>
          <label htmlFor="install-character" className="block text-xs text-text-secondary-alt mb-1">Character</label>
          <input
            id="install-character"
            type="text"
            value={character}
            onChange={(e) => setCharacter(e.target.value)}
            disabled={phase === "installing"}
            placeholder="e.g. Zarana"
            className="w-full bg-panel-inset border border-border focus:border-accent-start rounded px-2 py-1.5 text-sm text-white placeholder-gray-600 disabled:opacity-40 focus:outline-none"
          />
        </div>

        {destinationPreview && (
          <div className="text-xs text-text-secondary-alt">
            Will install to <code className="text-text-secondary font-mono">{destinationPreview}</code>
          </div>
        )}
      </section>

      {/* Step 3 — confirm */}
      <section className="bg-panel border border-border-subtle rounded-xl p-6 space-y-4">
        <h2 className="font-semibold text-text-primary-alt text-sm uppercase tracking-wide">
          3 — Install
        </h2>

        {(phase === "idle" || phase === "installing") && (
          <button
            onClick={install}
            disabled={!canInstall || phase === "installing"}
            className="flex items-center gap-2 px-5 py-3 rounded-lg text-sm font-medium bg-accent-end hover:bg-accent-start text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {phase === "installing" ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Installing…
              </>
            ) : (
              <>
                <Package size={14} />
                Install
              </>
            )}
          </button>
        )}

        {phase === "installed" && result && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-green-400">
              <Check size={16} />
              <span>
                Installed {result.file_count} file{result.file_count === 1 ? "" : "s"}
                {" "}({formatBytes(result.total_bytes)}) to{" "}
                <code className="text-green-300 font-mono">{result.dest}</code>
              </span>
            </div>

            {scanPhase === "idle" && (
              <button
                onClick={scanNow}
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-panel-secondary hover:bg-panel-secondary border border-border text-text-secondary text-xs transition-colors"
              >
                <ScanLine size={12} />
                Scan now
              </button>
            )}
            {scanPhase === "scanning" && (
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <Loader2 size={16} className="animate-spin text-indigo-400" />
                <span>{scanMsg || "scanning…"}</span>
              </div>
            )}
            {scanPhase === "done" && (
              <div className="flex items-center gap-2 text-sm text-green-400">
                <Check size={16} />
                <span>{scanMsg || "scan complete"}</span>
              </div>
            )}
            {scanPhase === "error" && (
              <div className="flex items-center gap-2 text-sm text-red-400">
                <AlertCircle size={16} />
                <span>{scanMsg || "scan failed"}</span>
              </div>
            )}

            <div>
              <button
                onClick={reset}
                className="px-4 py-2 rounded-lg bg-panel-secondary hover:bg-panel-secondary text-text-primary-alt2 text-sm transition-colors"
              >
                Install another
              </button>
            </div>
          </div>
        )}

        {phase === "error" && (
          <div className="space-y-4">
            <div
              role="alert"
              className="flex items-start gap-2.5"
              style={{
                border: "1px solid rgba(244,63,94,.3)",
                background: "rgba(244,63,94,.06)",
                borderRadius: 10,
                padding: "14px 16px",
              }}
            >
              <AlertCircle size={16} strokeWidth={2} className="shrink-0 mt-0.5" style={{ color: "#fda4af" }} />
              <div>
                <p style={{ margin: 0, color: "#fda4af", fontWeight: 600, fontSize: "13.5px" }}>
                  Install failed
                </p>
                <p style={{ margin: "2px 0 0", color: "#fca5b5", fontSize: "12.5px", lineHeight: 1.6 }}>
                  {error}
                </p>
              </div>
            </div>
            <button
              onClick={() => setPhase("idle")}
              className="btn-cta px-4 py-2 rounded-lg text-white text-sm font-semibold"
            >
              Try again
            </button>
          </div>
        )}
      </section>

      {picking && (
        <FolderPicker
          fileExtensions="zip"
          onSelect={(path) => {
            setSourcePath(path);
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}
