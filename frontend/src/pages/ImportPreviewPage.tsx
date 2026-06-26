import { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Inbox, RefreshCw, ChevronDown, ChevronRight, Check, Loader2,
  AlertCircle, Package, ArrowLeft, Download, ChevronLeft, Plus,
} from "lucide-react";
import { api, Library, ImportPreviewPack, SourceContentsEntry, Collection } from "../api/client";
import { useToast } from "../context/ToastContext";
import TagInput from "../components/TagInput";

type ImportStatus = "idle" | "running" | "done" | "error";

interface CardFields {
  creator: string;
  character: string;
  title: string;
  tags: string[];
  notes: string;
  sourceUrl: string;
  collectionIds: number[];
  images: string[];
}

const EMPTY_FIELDS: CardFields = {
  creator: "", character: "", title: "", tags: [], notes: "", sourceUrl: "", collectionIds: [], images: [],
};

function fieldsFromPack(p: ImportPreviewPack | undefined): CardFields {
  if (!p) return { ...EMPTY_FIELDS, tags: [], collectionIds: [], images: [] };
  return {
    creator: p.creator_name ?? "",
    character: p.character ?? "",
    title: p.title ?? "",
    tags: p.tags ?? [],
    notes: p.notes ?? "",
    sourceUrl: p.source_url ?? "",
    collectionIds: [],
    images: [],
  };
}

export default function ImportPreviewPage() {
  const [params] = useSearchParams();
  const source = params.get("source") ?? "";
  const { toast } = useToast();

  const [entries, setEntries] = useState<SourceContentsEntry[]>([]);
  const [isFlat, setIsFlat] = useState(false);
  const [flatFileCount, setFlatFileCount] = useState(0);
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [libraryId, setLibraryId] = useState<number | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  // configLoading: initial fetch of library list / mapping / collections
  const [configLoading, setConfigLoading] = useState(true);
  // scanning: "Scan for New Files" in flight
  const [scanning, setScanning] = useState(false);
  // hasScanned: true once the user has clicked "Scan for New Files" at least once
  const [hasScanned, setHasScanned] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Per-card state, keyed by the pack's source path.
  const [fields, setFields] = useState<Record<string, CardFields>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState<Record<string, ImportStatus>>({});
  const [progress, setProgress] = useState<Record<string, { models: number; files: number }>>({});
  const [fetching, setFetching] = useState<Record<string, boolean>>({});

  const [newColName, setNewColName] = useState("");
  const [creatingCol, setCreatingCol] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // Load just the config (library list, mapping, collections) — runs on mount.
  const loadConfig = useCallback(async () => {
    if (!source) { setError("No source folder specified."); setConfigLoading(false); return; }
    setConfigLoading(true);
    setError(null);
    try {
      const [libs, mapping, cols] = await Promise.all([
        api.scan.libraries(),
        api.import.getMapping(source),
        api.collections.list(),
      ]);
      setLibraries(libs);
      setLibraryId(mapping?.library_id ?? null);
      setCollections(cols);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load source configuration.");
    } finally {
      setConfigLoading(false);
    }
  }, [source]);

  // Load (or reload) the disk listing + inbox preview — called on scan/refresh.
  const loadContents = useCallback(async () => {
    if (!source) return;
    setScanning(true);
    setError(null);
    try {
      const [contents, preview] = await Promise.all([
        api.import.sourceContents(source),
        api.import.preview(source),
      ]);
      setEntries(contents.entries);
      setIsFlat(contents.is_flat);
      setFlatFileCount(contents.file_count);

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
      setHasScanned(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to scan the source folder.");
    } finally {
      setScanning(false);
    }
  }, [source]);

  useEffect(() => { loadConfig(); }, [loadConfig]);

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

  // Storefront scrape (#458): populate the card's metadata from the Source URL,
  // mirroring MetadataEditor. Scrape carries no `notes`, so Notes stays manual.
  const fetchMeta = async (path: string) => {
    const f = fields[path] ?? EMPTY_FIELDS;
    const url = f.sourceUrl.trim();
    if (!url) return;
    setFetching((m) => ({ ...m, [path]: true }));
    try {
      const s = await api.scrape.fetchUrl(url);
      // Collect all images: deduplicated union of thumbnail + image_urls.
      const allImages = [
        ...(s.thumbnail_url ? [s.thumbnail_url] : []),
        ...(s.image_urls ?? []),
      ].filter((u, i, arr) => arr.indexOf(u) === i);
      setField(path, {
        title: s.title || f.title,
        creator: s.creator_name || f.creator,
        sourceUrl: s.source_url || url,
        tags: [...new Set([...f.tags, ...s.tags])],
        images: allImages,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error && e.message.includes("400")
        ? "URL not recognised — only Gumroad, Cults3D and MyMiniFactory are supported."
        : "Couldn't fetch metadata from that URL.";
      toast(msg, "error");
    } finally {
      setFetching((m) => ({ ...m, [path]: false }));
    }
  };

  // Create a new collection and auto-select it for every currently-expanded card.
  const createCollection = async () => {
    const name = newColName.trim();
    if (!name || creatingCol) return;
    setCreatingCol(true);
    try {
      const col = await api.collections.create(name);
      setCollections((prev) => [...prev, col]);
      // Auto-select the new collection on all expanded cards.
      setFields((prev) => {
        const next = { ...prev };
        for (const path of Object.keys(next)) {
          if (expanded[path]) {
            next[path] = { ...next[path], collectionIds: [...next[path].collectionIds, col.id] };
          }
        }
        return next;
      });
      setNewColName("");
      toast(`Collection "${col.name}" created and selected.`, "success");
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Couldn't create collection.", "error");
    } finally {
      setCreatingCol(false);
    }
  };

  const waitForScan = (packPath: string) =>
    new Promise<void>((resolve, reject) => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.scan.status();
          setProgress((m) => ({
            ...m,
            [packPath]: { models: s.models_found ?? 0, files: s.files_found ?? 0 },
          }));
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
    setProgress((m) => ({ ...m, [entry.path]: { models: 0, files: 0 } }));
    try {
      await api.import.scanFolder(entry.path);
      await waitForScan(entry.path);
      // The just-ingested pack's models, fetched fresh.
      const preview = await api.import.preview(source);
      const ids = preview.packs
        .filter((p) => p.source_path === entry.path || (isFlat && p.source_path === source))
        .flatMap((p) => p.model_ids);
      const f = fields[entry.path] ?? EMPTY_FIELDS;
      // Download CDN gallery images into the pack folder before apply so they
      // travel to the library folder with the rest of the pack's files.
      if (f.images.length) {
        await api.import.downloadImages(entry.path, f.images);
      }
      if (ids.length) {
        const enrich: {
          creator_name?: string; character?: string; title?: string;
          notes?: string; source_url?: string;
        } = {};
        if (f.creator.trim()) enrich.creator_name = f.creator.trim();
        if (f.character.trim()) enrich.character = f.character.trim();
        if (f.title.trim()) enrich.title = f.title.trim();
        if (f.notes.trim()) enrich.notes = f.notes.trim();
        if (f.sourceUrl.trim()) enrich.source_url = f.sourceUrl.trim();
        if (Object.keys(enrich).length) await api.models.bulkEnrich(ids, enrich);
        if (f.tags.length) await api.models.bulkTag(ids, f.tags, []);
        // Collections need the post-ingest model ids, so they apply last (#458).
        for (const colId of f.collectionIds) await api.collections.bulkAddModels(colId, ids);
      }
      // Move the pack to the library immediately — no separate "Move to Library" step.
      const res = await api.import.apply(source);
      const libraryName = libraries.find((l) => l.id === libraryId)?.name ?? "library";
      if (res.moved_models > 0) {
        toast(`"${entry.name}" imported into ${libraryName}.`, "success");
        setStatus((m) => ({ ...m, [entry.path]: "done" }));
        await loadContents();
      } else if (res.skipped > 0) {
        const why = res.ineligible[0]?.reasons[0] ?? "ineligible";
        toast(`Skipped (${why}) — check creator/title are set.`, "error");
        setStatus((m) => ({ ...m, [entry.path]: "error" }));
      } else {
        toast(`Imported "${entry.name}".`, "success");
        setStatus((m) => ({ ...m, [entry.path]: "done" }));
        await loadContents();
      }
    } catch (e: unknown) {
      setStatus((m) => ({ ...m, [entry.path]: "error" }));
      toast(e instanceof Error ? e.message : `Couldn't import "${entry.name}".`, "error");
    }
  };

  // Only show packs that still have STL files on disk (file_count > 0).
  // After a successful import the pack folder is removed, so its count drops to 0.
  const allCards: SourceContentsEntry[] = isFlat
    ? [{ name: source.split(/[\\/]/).filter(Boolean).pop() || source, path: source, already_imported: false, file_count: flatFileCount }]
    : entries;
  const cards = allCards.filter((c) => c.file_count > 0 || status[c.path] === "running");

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-100 flex items-center gap-2">
            <Inbox size={22} className="text-indigo-400" />
            Import Preview
          </h1>
          <p className="mt-1 text-sm text-gray-400">
            Review packs, fill in metadata, and click Import to move each pack into your library.
          </p>
          {source && <p className="mt-1 text-xs font-mono text-gray-600 truncate">{source}</p>}
        </div>
        <button
          onClick={loadContents}
          disabled={scanning || configLoading}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium transition-colors shrink-0"
        >
          <RefreshCw size={14} className={scanning ? "animate-spin" : ""} />
          {hasScanned ? "Refresh" : "Scan for New Files"}
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

      {configLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={16} className="animate-spin text-indigo-400" /> Loading…
        </div>
      )}

      {scanning && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={16} className="animate-spin text-indigo-400" /> Scanning for packs…
        </div>
      )}

      {!configLoading && !hasScanned && !error && (
        <div className="text-sm text-gray-500 bg-gray-900 border border-gray-800 rounded-lg px-4 py-10 text-center space-y-2">
          <p>Click <strong className="text-gray-300">Scan for New Files</strong> to find packs ready to import.</p>
        </div>
      )}

      {hasScanned && !scanning && !error && cards.length === 0 && (
        <div className="text-sm text-gray-500 bg-gray-900 border border-gray-800 rounded-lg px-4 py-8 text-center">
          No packs found in this folder.
        </div>
      )}

      {hasScanned && <div className="space-y-3">
        {cards.map((c) => {
          const f = fields[c.path] ?? EMPTY_FIELDS;
          const st = status[c.path] ?? "idle";
          const prog = progress[c.path];
          const open = expanded[c.path] ?? false;
          return (
            <div key={c.path} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              {st === "running" && (
                <div className="h-1 w-full bg-gray-800 overflow-hidden">
                  <div className="h-full bg-indigo-500 animate-pulse w-full" />
                </div>
              )}
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
                {st === "running" && prog && (prog.models > 0 || prog.files > 0) && (
                  <span className="text-xs text-indigo-300 shrink-0 tabular-nums">
                    {prog.models}m / {prog.files}f
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
                <div className="border-t border-gray-800 px-4 py-3 space-y-3">
                  {f.images.length > 0 && <ImageRotator images={f.images} />}
                  <div className="grid grid-cols-2 gap-3">
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
                  <div className="col-span-2">
                    <Field label="Source URL">
                      <div className="flex gap-2">
                        <input value={f.sourceUrl} placeholder="https://…" type="url"
                          onChange={(e) => setField(c.path, { sourceUrl: e.target.value })}
                          className="flex-1 bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none" />
                        <button
                          onClick={() => fetchMeta(c.path)}
                          disabled={!f.sourceUrl.trim() || fetching[c.path]}
                          title="Fetch metadata from this URL"
                          className="flex items-center gap-1 text-xs px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 disabled:opacity-50 shrink-0"
                        >
                          {fetching[c.path] ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                          Fetch
                        </button>
                      </div>
                    </Field>
                  </div>
                  <div className="col-span-2">
                    <Field label="Notes">
                      <textarea value={f.notes} placeholder="Notes about this pack…" rows={2}
                        onChange={(e) => setField(c.path, { notes: e.target.value })}
                        className="w-full bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none resize-y" />
                    </Field>
                  </div>
                  <div className="col-span-2">
                    <Field label="Collections">
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {collections.map((col) => {
                          const on = f.collectionIds.includes(col.id);
                          return (
                            <button
                              key={col.id}
                              onClick={() => setField(c.path, {
                                collectionIds: on
                                  ? f.collectionIds.filter((id) => id !== col.id)
                                  : [...f.collectionIds, col.id],
                              })}
                              aria-pressed={on}
                              className={`text-xs px-2 py-1 rounded border transition-colors ${
                                on
                                  ? "bg-indigo-600/30 border-indigo-500 text-indigo-200"
                                  : "bg-gray-800 hover:bg-gray-700 border-gray-700 text-gray-400"
                              }`}
                            >
                              {col.name}
                            </button>
                          );
                        })}
                        {collections.length === 0 && (
                          <span className="text-xs text-gray-600 italic">No collections yet.</span>
                        )}
                      </div>
                      {/* Inline create */}
                      <div className="flex items-center gap-1.5 mt-1.5">
                        <input
                          type="text"
                          value={newColName}
                          onChange={(e) => setNewColName(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); createCollection(); } }}
                          placeholder="New collection…"
                          className="bg-gray-950 border border-gray-700 focus:border-indigo-500 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none w-40"
                        />
                        <button
                          onClick={createCollection}
                          disabled={!newColName.trim() || creatingCol}
                          className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 disabled:opacity-40 transition-colors"
                        >
                          <Plus size={11} /> Create
                        </button>
                      </div>
                    </Field>
                  </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>}

      <Link to="/import" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300">
        <ArrowLeft size={14} /> Choose a different folder
      </Link>
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

function ImageRotator({ images }: { images: string[] }) {
  const [idx, setIdx] = useState(0);
  const [fade, setFade] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const goTo = (next: number) => {
    setFade(false);
    setTimeout(() => {
      setIdx(next);
      setFade(true);
    }, 200);
  };

  useEffect(() => {
    if (images.length <= 1) return;
    timerRef.current = setInterval(() => {
      setIdx((i) => {
        const next = (i + 1) % images.length;
        setFade(false);
        setTimeout(() => setFade(true), 200);
        return next;
      });
    }, 5000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [images]);

  const prev = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    goTo((idx - 1 + images.length) % images.length);
  };

  const next = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    goTo((idx + 1) % images.length);
  };

  return (
    <div className="relative w-full rounded-lg overflow-hidden bg-gray-950 border border-gray-800" style={{ aspectRatio: "16/9" }}>
      <img
        key={idx}
        src={images[idx]}
        alt=""
        className="w-full h-full object-contain transition-opacity duration-200"
        style={{ opacity: fade ? 1 : 0 }}
      />
      {images.length > 1 && (
        <>
          <button
            onClick={prev}
            className="absolute left-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-black/50 hover:bg-black/70 text-white transition-colors"
            aria-label="Previous image"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={next}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-black/50 hover:bg-black/70 text-white transition-colors"
            aria-label="Next image"
          >
            <ChevronRight size={16} />
          </button>
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5">
            {images.map((_, i) => (
              <button
                key={i}
                onClick={() => { if (timerRef.current) clearInterval(timerRef.current); goTo(i); }}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${i === idx ? "bg-white" : "bg-white/40"}`}
                aria-label={`Image ${i + 1}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
