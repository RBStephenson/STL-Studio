import { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Inbox, RefreshCw, ChevronDown, ChevronRight, Check, Loader2,
  AlertCircle, Package, ArrowLeft,
} from "lucide-react";
import { api, Library, ImportPreviewPack, SourceContentsEntry } from "../api/client";
import { useToast } from "../context/ToastContext";
import TagInput from "../components/TagInput";

type ImportStatus = "idle" | "running" | "done" | "error";

interface CardFields {
  creator: string;
  character: string;
  title: string;
  tags: string[];
}

const EMPTY_FIELDS: CardFields = { creator: "", character: "", title: "", tags: [] };

function fieldsFromPack(p: ImportPreviewPack | undefined): CardFields {
  if (!p) return { ...EMPTY_FIELDS };
  return {
    creator: p.creator_name ?? "",
    character: p.character ?? "",
    title: p.title ?? "",
    tags: p.tags ?? [],
  };
}

export default function ImportPreviewPage() {
  const [params] = useSearchParams();
  const source = params.get("source") ?? "";
  const { toast } = useToast();

  const [entries, setEntries] = useState<SourceContentsEntry[]>([]);
  const [isFlat, setIsFlat] = useState(false);
  const [flatFileCount, setFlatFileCount] = useState(0); // root STL count for the flat card (#456)
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [libraryId, setLibraryId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-card state, keyed by the pack's source path.
  const [fields, setFields] = useState<Record<string, CardFields>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState<Record<string, ImportStatus>>({});

  const [applying, setApplying] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const load = useCallback(async () => {
    if (!source) { setError("No source folder specified."); setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const [contents, libs, mapping, preview] = await Promise.all([
        api.import.sourceContents(source),
        api.scan.libraries(),
        api.import.getMapping(source),
        api.import.preview(source),
      ]);
      setEntries(contents.entries);
      setIsFlat(contents.is_flat);
      setFlatFileCount(contents.file_count);
      setLibraries(libs);
      setLibraryId(mapping?.library_id ?? null);

      const packByPath = new Map(preview.packs.map((p) => [p.source_path, p]));
      const cards: SourceContentsEntry[] = contents.is_flat
        ? [{ name: contents.source.split(/[\\/]/).filter(Boolean).pop() || contents.source,
             path: contents.source, already_imported: preview.packs.length > 0,
             file_count: contents.file_count }]
        : contents.entries;
      setFields((prev) => {
        const next = { ...prev };
        for (const c of cards) if (!(c.path in next)) next[c.path] = fieldsFromPack(packByPath.get(c.path));
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load the source folder.");
    } finally {
      setLoading(false);
    }
  }, [source]);

  useEffect(() => { load(); }, [load]);

  const chooseLibrary = async (id: number) => {
    setLibraryId(id);
    try {
      await api.import.setMapping(source, id);
    } catch {
      toast("Couldn't save the library mapping — try again.", "error");
    }
  };

  const setField = (path: string, patch: Partial<CardFields>) =>
    setFields((m) => ({ ...m, [path]: { ...(m[path] ?? EMPTY_FIELDS), ...patch } }));

  const waitForScan = () =>
    new Promise<void>((resolve, reject) => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.scan.status();
          if (!s.running) {
            if (pollRef.current) clearInterval(pollRef.current);
            if (s.message?.startsWith("error:")) reject(new Error(s.message));
            else resolve();
          }
        } catch { /* transient — keep polling */ }
      }, 1200);
    });

  const importPack = async (entry: SourceContentsEntry) => {
    if (!libraryId) { toast("Pick a destination library first.", "error"); return; }
    setStatus((m) => ({ ...m, [entry.path]: "running" }));
    try {
      await api.import.scanFolder(entry.path);
      await waitForScan();
      // The just-ingested pack's models, fetched fresh.
      const preview = await api.import.preview(entry.path);
      const ids = preview.packs.flatMap((p) => p.model_ids);
      const f = fields[entry.path] ?? EMPTY_FIELDS;
      if (ids.length) {
        const enrich: { creator_name?: string; character?: string; title?: string } = {};
        if (f.creator.trim()) enrich.creator_name = f.creator.trim();
        if (f.character.trim()) enrich.character = f.character.trim();
        if (f.title.trim()) enrich.title = f.title.trim();
        if (Object.keys(enrich).length) await api.models.bulkEnrich(ids, enrich);
        if (f.tags.length) await api.models.bulkTag(ids, f.tags, []);
      }
      setStatus((m) => ({ ...m, [entry.path]: "done" }));
      toast(`Imported "${entry.name}".`, "success");
    } catch (e: unknown) {
      setStatus((m) => ({ ...m, [entry.path]: "error" }));
      toast(e instanceof Error ? e.message : `Couldn't import "${entry.name}".`, "error");
    }
  };

  const cards: SourceContentsEntry[] = isFlat
    ? [{ name: source.split(/[\\/]/).filter(Boolean).pop() || source, path: source, already_imported: false, file_count: flatFileCount }]
    : entries;

  const stagedCount = cards.filter((c) => c.already_imported || status[c.path] === "done").length;
  const libraryName = libraries.find((l) => l.id === libraryId)?.name ?? "library";

  const applyBatch = async () => {
    if (!libraryId) { toast("Pick a destination library first.", "error"); return; }
    setApplying(true);
    try {
      const res = await api.import.apply(source);
      if (res.moved_models > 0) toast(`Moved ${res.moved_models} pack(s) into ${libraryName}.`, "success");
      if (res.skipped > 0) {
        const why = res.ineligible[0]?.reasons[0] ?? "ineligible";
        toast(`${res.skipped} pack(s) skipped (${why}).`, res.moved_models > 0 ? "info" : "error");
      }
      if (res.moved_models === 0 && res.skipped === 0) toast("Nothing to move.", "info");
      await load();  // moved models lose is_inbox → leave the list
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Couldn't move the packs — check the destination is writable.", "error");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-100 flex items-center gap-2">
            <Inbox size={22} className="text-indigo-400" />
            Import Preview
          </h1>
          <p className="mt-1 text-sm text-gray-400">
            Review packs, set metadata, then import to your library.
          </p>
          {source && <p className="mt-1 text-xs font-mono text-gray-600 truncate">{source}</p>}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium transition-colors shrink-0"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Scan for New Files
        </button>
      </div>

      {/* Destination library (source-level, inherited by all packs) */}
      <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
        <label htmlFor="lib" className="text-sm text-gray-400 shrink-0">Library</label>
        <select
          id="lib"
          value={libraryId ?? ""}
          onChange={(e) => e.target.value && chooseLibrary(Number(e.target.value))}
          className="flex-1 bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2.5 py-1.5 text-sm text-gray-100 focus:outline-none"
        >
          <option value="" disabled>Select a destination library…</option>
          {libraries.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        {libraries.length === 0 && (
          <Link to="/settings" className="text-xs text-indigo-400 hover:text-indigo-300 shrink-0">
            Mark a folder as an import destination →
          </Link>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-400 bg-red-950/40 border border-red-900/60 rounded-lg px-4 py-3">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={16} className="animate-spin text-indigo-400" /> Loading…
        </div>
      )}

      {!loading && !error && cards.length === 0 && (
        <div className="text-sm text-gray-500 bg-gray-900 border border-gray-800 rounded-lg px-4 py-8 text-center">
          No packs found in this folder.
        </div>
      )}

      <div className="space-y-3">
        {cards.map((c) => {
          const f = fields[c.path] ?? EMPTY_FIELDS;
          const st = status[c.path] ?? "idle";
          const open = expanded[c.path] ?? false;
          return (
            <div key={c.path} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-3">
                <button
                  onClick={() => setExpanded((m) => ({ ...m, [c.path]: !open }))}
                  className="text-gray-500 hover:text-gray-300 shrink-0"
                  aria-label={open ? "Collapse" : "Expand"}
                >
                  {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                <Package size={16} className="text-indigo-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-100 truncate">{c.name}</div>
                  <div className="text-xs font-mono text-gray-600 truncate">{c.path}</div>
                </div>
                <span className="text-xs text-gray-500 shrink-0 tabular-nums" data-testid="pack-file-count">
                  {c.file_count} {c.file_count === 1 ? "file" : "files"}
                </span>
                {c.already_imported && st === "idle" && (
                  <span className="text-xs text-gray-500 shrink-0">imported</span>
                )}
                {st === "done" && (
                  <span className="flex items-center gap-1 text-xs text-green-400 shrink-0">
                    <Check size={13} /> Imported
                  </span>
                )}
                <button
                  onClick={() => importPack(c)}
                  disabled={st === "running" || !libraryId}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm font-medium transition-colors shrink-0"
                >
                  {st === "running"
                    ? <><Loader2 size={13} className="animate-spin" /> Importing…</>
                    : <>Import</>}
                </button>
              </div>

              {open && (
                <div className="border-t border-gray-800 px-4 py-3 grid grid-cols-2 gap-3">
                  <Field label="Creator">
                    <input value={f.creator} placeholder="Creator name"
                      onChange={(e) => setField(c.path, { creator: e.target.value })}
                      className="w-full bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none" />
                  </Field>
                  <Field label="Character / Group">
                    <input value={f.character} placeholder="Character or group"
                      onChange={(e) => setField(c.path, { character: e.target.value })}
                      className="w-full bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none" />
                  </Field>
                  <div className="col-span-2">
                    <Field label="Title">
                      <input value={f.title} placeholder="Title"
                        onChange={(e) => setField(c.path, { title: e.target.value })}
                        className="w-full bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none" />
                    </Field>
                  </div>
                  <div className="col-span-2">
                    <Field label="Tags">
                      <TagInput value={f.tags} onChange={(tags) => setField(c.path, { tags })} suggestions={[]} />
                    </Field>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <Link to="/import" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300">
        <ArrowLeft size={14} /> Choose a different folder
      </Link>

      {/* Batch apply — move staged (imported) packs into the mapped library */}
      {stagedCount > 0 && (
        <div className="fixed bottom-0 inset-x-0 z-40 flex justify-center pb-5 pointer-events-none">
          <div className="pointer-events-auto flex items-center gap-4 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl px-5 py-3">
            <span className="text-sm text-gray-300">
              {stagedCount} imported pack{stagedCount !== 1 ? "s" : ""} ready to move
            </span>
            <button
              onClick={applyBatch}
              disabled={applying || !libraryId}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm font-medium transition-colors"
            >
              {applying
                ? <><Loader2 size={14} className="animate-spin" /> Moving…</>
                : <>Move to {libraryName}</>}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</label>
      {children}
    </div>
  );
}
