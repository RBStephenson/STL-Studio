import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, ApiError, Guide, GuideCreateInput } from "../api/client";
import GuideMetaForm from "../components/guide/GuideMetaForm";
import { useToast } from "../context/ToastContext";
import ErrorState from "../components/ErrorState";
import { SkeletonBlock, SkeletonPanel } from "../components/SkeletonBlock";

export default function GuideEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const isNew = id === undefined;

  const [guide, setGuide] = useState<Guide | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadGuide = useCallback(async () => {
    if (isNew) return;
    setLoading(true);
    setLoadError(null);
    try {
      setGuide(await api.painting.guides.get(Number(id)));
    } catch (e) {
      setLoadError((e as Error)?.message || "Could not load this guide.");
    } finally {
      setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => { void loadGuide(); }, [loadGuide]);

  const save = async (value: GuideCreateInput) => {
    setBusy(true);
    setFormError(null);
    try {
      if (isNew) {
        const created = await api.painting.guides.create(value);
        toast("Guide created.", "success");
        navigate(`/painting/guides/${created.id}`);
      } else {
        // Metadata-only save: no `tabs` sent, so the content spine is untouched.
        const updated = await api.painting.guides.update(Number(id), value);
        toast("Guide saved.", "success");
        navigate(`/painting/guides/${updated.id}`);
      }
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 409
          ? "That slug is already taken — choose a different one."
          : (e as Error)?.message || "Could not save the guide.";
      setFormError(msg);
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <Link
        to={isNew ? "/painting/guides" : `/painting/guides/${id}`}
        className="inline-flex items-center gap-1 text-xs text-text-secondary-alt hover:text-text-primary-alt2 mb-4"
      >
        <ArrowLeft size={14} /> {isNew ? "All guides" : "Back to guide"}
      </Link>
      <h1 className="text-2xl font-bold text-white mb-6">
        {isNew ? "New guide" : "Edit guide"}
      </h1>

      {loading && (
        <SkeletonPanel className="space-y-4 rounded-lg border border-border-subtle p-5" data-testid="guide-editor-loading-skeleton">
          <SkeletonBlock className="h-4 w-24" />
          <SkeletonBlock className="h-10 w-full" />
          <SkeletonBlock className="h-4 w-20" />
          <SkeletonBlock className="h-10 w-full" />
        </SkeletonPanel>
      )}
      {loadError && (
        <ErrorState title="Couldn't load this guide" message={loadError} onRetry={() => void loadGuide()} />
      )}

      {!loading && !loadError && (
        <GuideMetaForm
          initial={guide ?? undefined}
          lockSlug={!isNew}
          submitLabel={isNew ? "Create guide" : "Save changes"}
          busy={busy}
          error={formError}
          onSubmit={save}
          onCancel={() =>
            navigate(isNew ? "/painting/guides" : `/painting/guides/${id}`)
          }
        />
      )}
    </div>
  );
}
