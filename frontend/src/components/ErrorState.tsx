import { AlertCircle } from "lucide-react";

// Shared error-state panel (design/README.md "New Since Last Handoff" —
// Complete Content/Loading/Empty/Error state coverage). Mirrors the
// dashed-panel empty-state layout (GuidesPage) but in the rose/destructive
// palette, with an optional Retry CTA wired to the caller's refetch/reload.
export default function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center text-center rounded-[14px] border border-dashed px-8 py-16"
      style={{ borderColor: "rgba(244,63,94,.3)", background: "#160c10" }}
    >
      <div
        className="flex items-center justify-center w-14 h-14 rounded-full mb-4"
        style={{ background: "rgba(244,63,94,.15)" }}
      >
        <AlertCircle size={22} strokeWidth={1.6} style={{ color: "var(--color-status-rose)" }} />
      </div>
      <p className="text-base font-bold text-text-primary-alt mb-2">{title}</p>
      <p className="text-[13px] leading-relaxed text-text-secondary-alt max-w-[320px] mb-6">
        {message}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 bg-panel-secondary hover:bg-panel-secondary border border-border text-text-primary-alt text-sm px-4 py-2 rounded transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
