import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Users, Zap, X, RefreshCw, Loader2, Plus, Trash2 } from "lucide-react";
import { api, Creator, ScanStatus } from "../api/client";
import StorefrontEnrich from "../components/StorefrontEnrich";
import RefreshEnrich from "../components/RefreshEnrich";
import CreateCreatorModal from "../components/CreateCreatorModal";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import { errMsg } from "../utils/err";

export default function Creators() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [enriching, setEnriching] = useState<Creator | null>(null);
  const [search, setSearch] = useState("");
  const [scanningId, setScanningId] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<"name" | "models">("name");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const { toast } = useToast();
  const confirm = useConfirm();

  const loadCreators = () => {
    setLoading(true);
    setLoadError(null);
    return api.models.creators()
      .then(setCreators)
      .catch((e) => setLoadError(errMsg(e) || "Could not load creators."))
      .finally(() => setLoading(false));
  };
  useEffect(() => { loadCreators(); }, []);

  const onCreated = (creator: Creator) => {
    setCreators((prev) => [...prev, creator]);
    toast(`Added creator "${creator.name}"`, "success");
  };

  const rescan = async (c: Creator) => {
    if (scanningId !== null) return;  // a scan is already running
    setScanningId(c.id);
    try {
      await api.scan.startCreator(c.id);
      // Poll until the scan finishes, then refresh the model counts.
      let last: ScanStatus | null = null;
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        last = await api.scan.status();
        if (!last.running) break;
      }
      await loadCreators();
      // Announce the backend's completion summary (#283).
      toast(last?.message || `Rescanned ${c.name}.`, "success");
    } catch {
      /* ignore — e.g. another scan started elsewhere */
    } finally {
      setScanningId(null);
    }
  };

  const deleteCreator = async (c: Creator) => {
    if (deletingId !== null) return;
    const ok = await confirm({
      title: "Delete this creator?",
      message: `"${c.name}" will be permanently deleted. This cannot be undone.`,
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    setDeletingId(c.id);
    try {
      await api.models.deleteCreator(c.id);
      setCreators((prev) => prev.filter((x) => x.id !== c.id));
      toast(`"${c.name}" deleted.`, "success");
    } catch (e) {
      toast(errMsg(e) || "Couldn't delete creator — try again.", "error");
    } finally {
      setDeletingId(null);
    }
  };

  const filtered = creators
    .filter((c) => !search || c.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) =>
      sortBy === "name"
        ? a.name.localeCompare(b.name)
        : b.model_count - a.model_count
    );

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Users size={20} className="text-indigo-400" />
          <h1 className="text-2xl font-bold text-text-primary">Creators</h1>
          <span className="text-sm text-text-secondary-alt ml-1">({creators.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <RefreshEnrich scopeLabel="your whole library" />
          <div className="flex rounded border border-border overflow-hidden text-xs">
            <button
              onClick={() => setSortBy("name")}
              className={`px-3 py-1.5 transition-colors ${sortBy === "name" ? "bg-accent-end text-white" : "text-text-secondary hover:text-text-primary hover:bg-panel-secondary"}`}
            >A–Z</button>
            <button
              onClick={() => setSortBy("models")}
              className={`px-3 py-1.5 transition-colors ${sortBy === "models" ? "bg-accent-end text-white" : "text-text-secondary hover:text-text-primary hover:bg-panel-secondary"}`}
            >Most models</button>
          </div>
          <input
            type="text"
            placeholder="Search creators…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-panel border border-border rounded px-3 py-1.5 text-sm text-text-primary placeholder-gray-600 focus:outline-none focus:border-accent-start w-48"
          />
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-text-primary-alt2 text-sm transition-colors"
            title="Add a creator without waiting for a scan to find one"
          >
            <Plus size={14} /> Add Creator
          </button>
        </div>
      </div>

      {adding && (
        <CreateCreatorModal onClose={() => setAdding(false)} onCreated={onCreated} />
      )}

      {/* Storefront enrich panel */}
      {enriching && (
        <div className="mb-6">
          <StorefrontEnrich
            creatorId={enriching.id}
            creatorName={enriching.name}
            onDone={() => setEnriching(null)}
          />
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {Array.from({ length: 15 }).map((_, i) => (
            <div
              key={i}
              className="relative overflow-hidden rounded-lg"
              style={{ height: 98, background: "#141519", border: "1px solid #1a1b21" }}
            >
              <div className="stl-shimmer-overlay" />
            </div>
          ))}
        </div>
      ) : loadError ? (
        <ErrorState title="Couldn't load creators" message={loadError} onRetry={loadCreators} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Users}
          heading="No creators found"
          body="Nothing matches your search or filters. Try a different term, or add a creator manually."
          primaryAction={{ label: "Add creator", onClick: () => setAdding(true), icon: Plus }}
        />
      ) : (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
        {filtered.map((c) => (
          <div
            key={c.id}
            className={`group relative bg-panel border rounded-lg overflow-hidden flex flex-col transition-colors ${
              enriching?.id === c.id ? "border-accent-start" : "border-border-subtle hover:border-accent-start"
            }`}
          >
            <button
              onClick={() => deleteCreator(c)}
              disabled={deletingId !== null}
              title={`Delete ${c.name}`}
              aria-label={`Delete ${c.name}`}
              className={`absolute top-2 right-2 z-10 p-1.5 rounded bg-black/60 hover:bg-red-950/80 text-text-primary-alt2 hover:text-red-400 focus-visible:opacity-100 transition-opacity disabled:opacity-40 ${
                deletingId === c.id ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              }`}
            >
              {deletingId === c.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
            </button>
            <Link
              to={`/?creator_id=${c.id}`}
              className="flex-1 p-4 flex flex-col gap-1 hover:bg-panel-secondary/50 transition-colors"
              title={`Browse ${c.name}'s models`}
            >
              <span className="font-medium text-text-primary truncate group-hover:text-indigo-300 transition-colors">
                {c.name}
              </span>
              <span className="text-xs text-text-secondary-alt">{c.model_count} models →</span>
            </Link>
            <div className="flex border-t border-border-subtle divide-x divide-gray-800">
              <button
                onClick={() => rescan(c)}
                disabled={scanningId !== null}
                title={scanningId !== null ? "A scan is already running" : `Rescan ${c.name}`}
                className="flex-1 flex items-center justify-center gap-1 text-xs text-text-muted hover:text-emerald-400 transition-colors px-2 py-2 hover:bg-panel-secondary/30 disabled:opacity-40 disabled:hover:text-text-muted disabled:hover:bg-transparent"
              >
                {scanningId === c.id
                  ? <><Loader2 size={11} className="animate-spin" /> Scanning…</>
                  : <><RefreshCw size={11} /> Rescan</>
                }
              </button>
              <button
                onClick={() => setEnriching(enriching?.id === c.id ? null : c)}
                className="flex-1 flex items-center justify-center gap-1 text-xs text-text-muted hover:text-indigo-400 transition-colors px-2 py-2 hover:bg-panel-secondary/30"
              >
                {enriching?.id === c.id
                  ? <><X size={11} /> Close</>
                  : <><Zap size={11} /> Enrich</>
                }
              </button>
            </div>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}
