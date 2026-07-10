import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, ApiError, Guide, GuideCreateInput } from "../api/client";
import GuideMetaForm from "../components/guide/GuideMetaForm";
import { useToast } from "../context/ToastContext";

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

  useEffect(() => {
    if (isNew) return;
    let alive = true;
    setLoading(true);
    setLoadError(null);
    api.painting.guides
      .get(Number(id))
      .then((g) => { if (alive) setGuide(g); })
      .catch((e) => { if (alive) setLoadError(e?.message || "Could not load this guide."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [id, isNew]);

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

      {loading && <p className="text-sm text-text-secondary-alt">Loading…</p>}
      {loadError && <p role="alert" className="text-sm text-rose-400">{loadError}</p>}

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
