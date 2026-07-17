import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, Sparkles, X } from "lucide-react";
import {
  api,
  ApiError,
  Guide,
  GuideDraftStatus,
  GuideTab,
  StepInput,
  TabInput,
} from "../api/client";
import GuideReader from "../components/guide/GuideReader";
import GuideValidationPanel from "../components/guide/GuideValidationPanel";
import PaintPicker, { PickedPaint } from "../components/guide/PaintPicker";
import ReferenceImageUpload from "../components/guide/ReferenceImageUpload";
import { useToast } from "../context/ToastContext";
import ErrorState from "../components/ErrorState";
import { SkeletonBlock, SkeletonPanel } from "../components/SkeletonBlock";

const POLL_MS = 1200;

// A paint entry (swatch or mix component) inside a draft step — name-only until
// reconciled. `mix_components` isn't on the TS StepInput but rides in the draft
// JSON, so the resolver walks both arrays through this loose shape.
type PaintEntry = { paint_id?: number | null; name?: string | null };

// Bind every name-only entry whose `name` matches a chosen resolution to that
// paint's id, across the whole draft tree. Returns a fresh copy; input untouched.
function applyResolutions(tabs: TabInput[], resolutions: Record<string, PickedPaint>): TabInput[] {
  const fix = (entry: PaintEntry): PaintEntry => {
    if (entry.paint_id == null && entry.name && resolutions[entry.name]) {
      return { ...entry, paint_id: resolutions[entry.name].id, name: null };
    }
    return entry;
  };
  return tabs.map((tab) => ({
    ...tab,
    phases: (tab.phases ?? []).map((phase) => ({
      ...phase,
      steps: (phase.steps ?? []).map((step) => {
        const s = step as StepInput & { mix_components?: PaintEntry[] };
        return {
          ...s,
          swatches: (s.swatches ?? []).map(fix),
          ...(s.mix_components ? { mix_components: s.mix_components.map(fix) } : {}),
        };
      }),
    })),
  })) as TabInput[];
}

// The draft tabs arrive as TabInput (no row ids); GuideReader keys its lists on
// `.id`. Stamp stable synthetic ids so the proposal renders without key clashes.
function withSyntheticIds(tabs: TabInput[]): GuideTab[] {
  let n = 0;
  const next = () => --n; // negative ids never collide with real rows
  return (tabs as unknown as GuideTab[]).map((tab) => ({
    ...tab,
    id: next(),
    phases: (tab.phases ?? []).map((phase) => ({
      ...phase,
      id: next(),
      steps: (phase.steps ?? []).map((step) => ({
        ...step,
        id: next(),
        swatches: (step.swatches ?? []).map((s) => ({ ...s, id: next() })),
        mix_components: (step.mix_components ?? []).map((m) => ({ ...m, id: next() })),
      })),
    })),
  }));
}

export default function GuideDraftReviewPage() {
  const { id } = useParams<{ id: string }>();
  const guideId = Number(id);
  const navigate = useNavigate();
  const { toast } = useToast();

  const [guide, setGuide] = useState<Guide | null>(null);
  const [refImageId, setRefImageId] = useState<number | null>(null);
  const [job, setJob] = useState<GuideDraftStatus | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  // Unresolved paint name -> chosen shelf paint, applied to the draft on Accept.
  const [resolutions, setResolutions] = useState<Record<string, PickedPaint>>({});
  const [forcing, setForcing] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [loadingGuide, setLoadingGuide] = useState(true);

  const poll = useCallback(async () => {
    try {
      const status = await api.painting.guides.draftStatus(guideId);
      setJob(status);
      if (status.status === "running") {
        pollRef.current = setTimeout(poll, POLL_MS);
      }
    } catch (e) {
      setFatal((e as Error)?.message || "Lost contact with the draft job.");
    }
  }, [guideId]);

  // Load the guide (for the diff + the attached reference image). Generation is
  // user-triggered (#536) so an attached image reaches vision on the first pass.
  const loadGuide = useCallback(async () => {
    setLoadingGuide(true);
    setFatal(null);
    try {
      const loaded = await api.painting.guides.get(guideId);
      setGuide(loaded);
      setRefImageId(loaded.reference_image_id);
    } catch (e) {
      setFatal((e as Error)?.message || "Could not load the guide.");
    } finally {
      setLoadingGuide(false);
    }
  }, [guideId]);

  useEffect(() => {
    void loadGuide();
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [loadGuide]);

  const generate = () => {
    setFatal(null);
    api.painting.guides.startDraft(guideId).then(
      (status) => { setJob(status); if (status.status === "running") poll(); },
      (e) => {
        if (e instanceof ApiError && e.status === 409) {
          // A job is already generating for this guide — attach and poll.
          poll();
        } else if (e instanceof ApiError && e.status === 503) {
          setFatal(
            "No AI API key is configured. Add one under Settings → Painting Guides, then try again.",
          );
        } else {
          setFatal((e as Error)?.message || "Could not start draft generation.");
        }
      },
    );
  };

  const resolve = (name: string, paint: PickedPaint | null) =>
    setResolutions((r) => {
      const next = { ...r };
      if (paint) next[name] = paint;
      else delete next[name];
      return next;
    });

  // Force-add an unresolved paint to the shelf, then use it as the resolution.
  const forceAdd = async (name: string) => {
    setForcing(name);
    try {
      const paint = await api.painting.paints.forceAdd(name, null);
      resolve(name, { id: paint.id, name: paint.name, code: paint.code, hex: paint.hex });
      toast(`Added “${name}” to your shelf.`, "success");
    } catch {
      toast(`Couldn't add “${name}” — try again.`, "error");
    } finally {
      setForcing(null);
    }
  };

  const accept = async () => {
    if (!job?.draft) return;
    setAccepting(true);
    try {
      // Bind any resolved unresolved-paints before committing the spine.
      const tabs = applyResolutions(job.draft.tabs, resolutions);
      await api.painting.guides.update(guideId, { tabs });
      toast("Draft accepted. Refine it below.", "success");
      navigate(`/painting/guides/${guideId}/content`);
    } catch (e) {
      setFatal((e as Error)?.message || "Could not accept the draft.");
      setAccepting(false);
    }
  };

  // Unique unresolved paint names (the same name can recur across steps).
  const unresolvedNames = job ? [...new Set(job.unresolved.map((u) => u.name))] : [];

  const proposed: GuideTab[] | null = job?.draft ? withSyntheticIds(job.draft.tabs) : null;
  const running = job?.status === "running";
  // Pre-generation: no job yet, or the last attempt errored (offer a retry).
  const preGen = !job || job.status === "error";

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <Link to={`/painting/guides/${guideId}/content`} className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 mb-4">
        <ArrowLeft size={14} /> Back to editor
      </Link>

      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1 flex items-center gap-2">
            <Sparkles size={20} className="text-indigo-400" /> Review AI draft
          </h1>
          {guide && <p className="text-sm text-gray-500">{guide.title}</p>}
        </div>
        {job?.status === "done" && proposed && (
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => navigate(`/painting/guides/${guideId}/content`)}
              className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 rounded px-3 py-1.5"
            >
              <X size={15} /> Discard
            </button>
            <button
              type="button"
              onClick={accept}
              disabled={accepting}
              className="inline-flex items-center gap-1.5 text-sm text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded px-3 py-1.5"
            >
              <Check size={15} /> {accepting ? "Accepting…" : "Accept into editor"}
            </button>
          </div>
        )}
      </div>

      {loadingGuide && (
        <SkeletonPanel className="max-w-xl space-y-4 rounded-lg border border-gray-800 p-5" data-testid="guide-draft-loading-skeleton">
          <SkeletonBlock className="h-4 w-32" />
          <SkeletonBlock className="h-28 w-full" />
          <SkeletonBlock className="h-9 w-36" />
        </SkeletonPanel>
      )}
      {!loadingGuide && fatal && !guide && (
        <ErrorState title="Couldn't load this guide" message={fatal} onRetry={() => void loadGuide()} />
      )}
      {guide && fatal && <p role="alert" className="text-sm text-rose-400 mb-4">{fatal}</p>}

      {job?.status === "error" && (
        <p role="alert" className="text-sm text-rose-400 border border-rose-900/50 rounded-lg p-4 mb-4">
          Generation failed: {job.error}
        </p>
      )}

      {preGen && guide && (
        <div className="max-w-xl space-y-5 border border-gray-800 rounded-lg p-5">
          <div>
            <h2 className="text-sm font-semibold text-gray-300 mb-1">Reference image <span className="text-gray-600 font-normal">(optional)</span></h2>
            <p className="text-xs text-gray-500 mb-3">
              Attach a photo of the figure or subject — Claude analyzes it for skin tone, value, and texture while drafting.
            </p>
            <ReferenceImageUpload
              guideId={guideId}
              referenceImageId={refImageId}
              onChange={setRefImageId}
            />
          </div>
          <button
            type="button"
            onClick={generate}
            className="inline-flex items-center gap-2 text-sm text-white bg-indigo-600 hover:bg-indigo-500 rounded px-4 py-2"
          >
            <Sparkles size={16} /> {job?.status === "error" ? "Try again" : "Generate draft"}
          </button>
        </div>
      )}

      {running && (
        <div className="flex items-center gap-3 text-sm text-gray-400 border border-gray-800 rounded-lg p-6">
          <Sparkles size={16} className="text-indigo-400 animate-pulse" />
          Generating a draft from your Paint Shelf… this can take a moment.
        </div>
      )}

      {job?.status === "done" && proposed && guide && (
        <div className="space-y-4">
          <GuideValidationPanel result={{ ok: !job.flags.some((f) => f.severity === "block"), flags: job.flags }} loading={false} />

          {unresolvedNames.length > 0 && (
            <div className="border border-amber-900/50 bg-amber-950/20 rounded-lg p-3 text-xs text-amber-300">
              <p className="font-medium mb-2">
                {unresolvedNames.length} paint{unresolvedNames.length === 1 ? "" : "s"} couldn't be matched to your shelf —
                bind each to a shelf paint or add it, or leave it (kept by name).
              </p>
              <ul className="space-y-1.5">
                {unresolvedNames.map((name) => {
                  const picked = resolutions[name] ?? null;
                  return (
                    <li key={name} className="flex items-center gap-2 flex-wrap">
                      <span className="text-amber-200">{name}</span>
                      <span className="text-amber-200/40">→</span>
                      <PaintPicker value={picked} onChange={(p) => resolve(name, p)} />
                      {!picked && (
                        <button
                          type="button"
                          onClick={() => forceAdd(name)}
                          disabled={forcing === name}
                          className="text-[11px] px-2 py-1 rounded border border-amber-800/60 text-amber-200 hover:bg-amber-900/30 disabled:opacity-50"
                        >
                          {forcing === name ? "Adding…" : "Add to shelf"}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <div className="lg:grid lg:grid-cols-2 lg:gap-6 lg:items-start">
            <div>
              <div className="text-[11px] uppercase tracking-wide text-indigo-400 mb-2">Proposed draft</div>
              <div className="border border-indigo-900/40 rounded-lg overflow-auto max-h-[calc(100vh-12rem)]">
                <GuideReader guide={{ ...guide, tabs: proposed }} />
              </div>
            </div>
            <div className="hidden lg:block mt-6 lg:mt-0">
              <div className="text-[11px] uppercase tracking-wide text-gray-500 mb-2">
                Current content {guide.tabs.length === 0 && "(empty)"}
              </div>
              <div className="border border-gray-800 rounded-lg overflow-auto max-h-[calc(100vh-12rem)]">
                {guide.tabs.length === 0
                  ? <p className="text-sm text-gray-600 p-6">This guide has no content yet — accepting will fill it.</p>
                  : <GuideReader guide={guide} />}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
