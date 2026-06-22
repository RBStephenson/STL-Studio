import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { api, ApiError, GuideScale, Model } from "../api/client";
import ModelSearchPicker from "../components/guide/ModelSearchPicker";
import { useToast } from "../context/ToastContext";

const SCALES: GuideScale[] = ["1:6", "1:12", "75mm", "28mm", "bust", "other"];

type Step = 1 | 2 | 3;

export default function GuideWizardPage() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [step, setStep] = useState<Step>(1);

  // Step 1 — Basics
  const [title, setTitle] = useState("");
  const [scale, setScale] = useState<GuideScale | "">("");
  const [categoryLabel, setCategoryLabel] = useState("");
  const [titleError, setTitleError] = useState(false);

  // Step 2 — Model link
  const [linkedModel, setLinkedModel] = useState<Model | null>(null);

  // Submit
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const goNext = () => {
    if (step === 1) {
      if (!title.trim()) { setTitleError(true); return; }
      setStep(2);
    } else if (step === 2) {
      setStep(3);
    }
  };

  const goBack = () => {
    setStep((s) => (s - 1) as Step);
    setError(null);
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const slug = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
      const guide = await api.painting.guides.create({
        slug,
        title: title.trim(),
        category_label: categoryLabel.trim() || null,
        scale: scale || null,
        model_id: linkedModel?.id ?? null,
        status: "draft",
      });
      toast("Guide created. Add your content below.", "success");
      navigate(`/painting/guides/${guide.id}/content`);
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 409
          ? "That slug is already taken — edit the title slightly."
          : (e as Error)?.message || "Could not create the guide.";
      setError(msg);
      setBusy(false);
    }
  };

  const field = "w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none";
  const labelCls = "block text-xs font-medium text-gray-400 mb-1";

  return (
    <div className="max-w-lg mx-auto px-4 py-8">
      <Link
        to="/painting/guides"
        className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 mb-4"
      >
        <ArrowLeft size={14} /> All guides
      </Link>
      <h1 className="text-2xl font-bold text-white mb-1">New guide</h1>
      <p className="text-sm text-gray-500 mb-6">Step {step} of 3</p>

      <div className="flex gap-1.5 mb-8" aria-hidden="true">
        {([1, 2, 3] as const).map((n) => (
          <div
            key={n}
            className={`h-1 flex-1 rounded-full transition-colors ${n <= step ? "bg-indigo-500" : "bg-gray-700"}`}
          />
        ))}
      </div>

      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-300">Basics</h2>
          <div>
            <label className={labelCls} htmlFor="wiz-title">Title *</label>
            <input
              id="wiz-title"
              className={field}
              value={title}
              onChange={(e) => { setTitle(e.target.value); setTitleError(false); }}
              placeholder="e.g. RoboCop (1987)"
              autoFocus
            />
            {titleError && (
              <p role="alert" className="mt-1 text-xs text-rose-400">A title is required.</p>
            )}
          </div>
          <div>
            <label className={labelCls} htmlFor="wiz-scale">Scale</label>
            <select
              id="wiz-scale"
              className={field}
              value={scale}
              onChange={(e) => setScale(e.target.value as GuideScale | "")}
            >
              <option value="">—</option>
              {SCALES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className={labelCls} htmlFor="wiz-category">Category label</label>
            <input
              id="wiz-category"
              className={field}
              value={categoryLabel}
              onChange={(e) => setCategoryLabel(e.target.value)}
              placeholder="e.g. figure-painting, sci-fi"
            />
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-300">
            Link to a model{" "}
            <span className="text-gray-600 font-normal">(optional)</span>
          </h2>
          <p className="text-xs text-gray-500">
            Ties this guide to a model in your library. Skip to link it later.
          </p>
          <ModelSearchPicker value={linkedModel} onChange={setLinkedModel} />
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-300">Options</h2>

          <div className="border border-gray-800 rounded p-4 space-y-3">
            <label className="flex items-start gap-3 cursor-not-allowed opacity-40">
              <input type="checkbox" disabled className="mt-0.5 accent-indigo-500" />
              <div>
                <span className="text-sm text-gray-300 block">Generate AI draft</span>
                <span className="text-xs text-gray-500">
                  Use Claude to create a painting guide draft from your shelf
                </span>
              </div>
            </label>
            <label className="flex items-start gap-3 cursor-not-allowed opacity-40">
              <input type="checkbox" disabled className="mt-0.5 accent-indigo-500" />
              <div>
                <span className="text-sm text-gray-300 block">Generate reference images</span>
                <span className="text-xs text-gray-500">
                  Pull reference images from the model files
                </span>
              </div>
            </label>
            <p className="text-xs text-gray-600 pt-1">AI features arrive in a future release.</p>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded p-3 text-xs text-gray-500 space-y-0.5">
            <p><span className="text-gray-400">Title:</span> {title}</p>
            {scale && <p><span className="text-gray-400">Scale:</span> {scale}</p>}
            {categoryLabel && <p><span className="text-gray-400">Category:</span> {categoryLabel}</p>}
            {linkedModel && (
              <p><span className="text-gray-400">Model:</span> {linkedModel.title || linkedModel.name}</p>
            )}
          </div>

          {error && (
            <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">
              {error}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 mt-8">
        {step > 1 ? (
          <button
            type="button"
            onClick={goBack}
            disabled={busy}
            className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 px-3 py-2 disabled:opacity-50"
          >
            <ArrowLeft size={14} /> Back
          </button>
        ) : (
          <div />
        )}

        {step < 3 ? (
          <button
            type="button"
            onClick={goNext}
            className="inline-flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-4 py-2 rounded transition-colors"
          >
            Next <ArrowRight size={14} />
          </button>
        ) : (
          <button
            type="button"
            onClick={create}
            disabled={busy}
            className="inline-flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-4 py-2 rounded transition-colors disabled:opacity-50"
          >
            <Check size={14} /> Create guide
          </button>
        )}
      </div>
    </div>
  );
}
