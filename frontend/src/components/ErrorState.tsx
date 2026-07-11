import { AlertCircle } from "lucide-react";

// Shared error-state panel (design/README.md "New Since Last Handoff" —
// Complete Content/Loading/Empty/Error state coverage). Mirrors the
// dashed-panel empty-state layout (GuidesPage) but in the rose/destructive
// palette, with an optional Retry CTA wired to the caller's refetch/reload.
export default function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retryLabel = "Retry",
  padding = "64px 32px",
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  padding?: string;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center text-center rounded-[14px] border border-dashed"
      style={{ borderColor: "rgba(244,63,94,.3)", background: "#160c10", padding }}
    >
      <div
        className="flex items-center justify-center w-14 h-14 rounded-full mb-[18px]"
        style={{ background: "rgba(244,63,94,.12)" }}
      >
        <AlertCircle size={24} strokeWidth={1.8} style={{ color: "#fda4af" }} />
      </div>
      <p style={{ margin: "0 0 5px", fontSize: 16, fontWeight: 700, color: "#e5e6ea" }}>{title}</p>
      <p
        style={{
          margin: "0 0 20px",
          fontSize: 13,
          color: "#6b7080",
          maxWidth: 340,
          lineHeight: 1.6,
        }}
      >
        {message}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="btn-cta"
          style={{
            padding: "9px 17px",
            borderRadius: 8,
            border: "none",
            color: "#fff",
            fontSize: "12.5px",
            fontWeight: 600,
          }}
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}
