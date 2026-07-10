import { useState } from "react";
import { ImagePlus, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError } from "../../api/client";
import { useToast } from "../../context/ToastContext";
import { downscaleForUpload } from "../../lib/imageUpload";

const ACCEPT = "image/png,image/jpeg,image/webp,image/gif";
const MAX_BYTES = 10 * 1024 * 1024; // mirror the backend cap (#535)
const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

/**
 * Attach / preview / replace / remove a guide's reference image (#536). The
 * bytes feed Claude vision at draft time (#535). Self-contained: it owns the
 * upload calls and reports the resulting reference-image id (or null) up via
 * `onChange` so the parent can keep the guide in sync.
 */
export default function ReferenceImageUpload({
  guideId,
  referenceImageId,
  onChange,
}: {
  guideId: number;
  referenceImageId: number | null;
  onChange: (referenceImageId: number | null) => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const upload = async (file: File) => {
    if (!ALLOWED_TYPES.has(file.type)) {
      toast("Use a PNG, JPEG, WebP, or GIF image.", "error");
      return;
    }
    setBusy(true);
    // Downscale a large original before upload; Claude vision resizes reference
    // images to ~1568px anyway, so this keeps quality and clears the size cap.
    const toUpload = await downscaleForUpload(file);
    if (toUpload.size > MAX_BYTES) {
      toast("Image is too large even after resizing — try a smaller file.", "error");
      setBusy(false);
      return;
    }
    try {
      const img = await api.painting.guides.uploadReferenceImage(guideId, toUpload);
      onChange(img.id);
      toast("Reference image attached.", "success");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Upload failed — try again.";
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.painting.guides.deleteReferenceImage(guideId);
      onChange(null);
      toast("Reference image removed.", "success");
    } catch {
      toast("Couldn't remove the image — try again.", "error");
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  };

  if (referenceImageId !== null) {
    return (
      <div className="space-y-2">
        <div className="relative inline-block">
          <img
            src={api.painting.guides.referenceImageUrl(guideId, referenceImageId)}
            alt="Reference"
            className="max-h-48 rounded-lg border border-border object-contain"
          />
          {busy && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/50 rounded-lg">
              <Loader2 size={20} className="animate-spin text-text-primary-alt" />
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-1.5 text-xs text-text-primary-alt2 border border-border rounded px-2.5 py-1.5 cursor-pointer hover:border-indigo-600">
            <RefreshCw size={13} /> Replace
            <input
              type="file"
              accept={ACCEPT}
              className="hidden"
              data-testid="reference-image-input"
              disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }}
            />
          </label>
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="inline-flex items-center gap-1.5 text-xs text-rose-300 border border-rose-900/60 rounded px-2.5 py-1.5 hover:bg-rose-950/30 disabled:opacity-50"
          >
            <Trash2 size={13} /> Remove
          </button>
        </div>
      </div>
    );
  }

  return (
    <label
      data-testid="reference-image-dropzone"
      onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={`flex flex-col items-center gap-2 border border-dashed rounded-lg px-6 py-6 text-center transition-colors ${
        busy ? "opacity-60 border-border" : "cursor-pointer"
      } ${dragOver ? "border-accent-start bg-indigo-950/30" : "border-border hover:border-indigo-600"}`}
    >
      {busy ? <Loader2 size={20} className="animate-spin text-indigo-400" /> : <ImagePlus size={20} className="text-indigo-400" />}
      <span className="text-sm text-text-primary-alt2">{busy ? "Uploading…" : "Choose or drop a reference image"}</span>
      <span className="text-xs text-text-muted">PNG, JPEG, WebP, or GIF — up to 10 MB</span>
      <input
        type="file"
        accept={ACCEPT}
        className="hidden"
        data-testid="reference-image-input"
        disabled={busy}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }}
      />
    </label>
  );
}
