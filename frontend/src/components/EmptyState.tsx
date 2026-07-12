import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

// Shared empty-state panel (design/STATES.md "Shared visual pattern"). One
// container recipe for every Empty state in the app — only icon tint, copy,
// and CTAs change per screen.
const TINTS = {
  indigo: { background: "#141726", icon: "#818cf8" },
  violet: { background: "#26163a", icon: "#e879f9" },
  sky: { background: "#0c2233", icon: "#7dd3fc" },
  green: { background: "#0f2417", icon: "#6ee7b7" },
} as const;

export type EmptyStateTint = keyof typeof TINTS;

export default function EmptyState({
  icon: Icon,
  tint = "indigo",
  heading,
  body,
  primaryAction,
  secondaryAction,
  padding = "64px 32px",
}: {
  icon: LucideIcon;
  tint?: EmptyStateTint;
  heading: ReactNode;
  body: ReactNode;
  primaryAction?: { label: ReactNode; onClick: () => void; icon?: LucideIcon; disabled?: boolean };
  secondaryAction?: { label: ReactNode; onClick: () => void };
  padding?: string;
}) {
  const { background, icon } = TINTS[tint];
  const PrimaryIcon = primaryAction?.icon;
  return (
    <div
      className="flex flex-col items-center justify-center text-center rounded-[14px] border border-dashed max-w-xl mx-auto"
      style={{ borderColor: "#1e2027", background: "#0e0f13", padding }}
    >
      <div
        className="flex items-center justify-center w-14 h-14 rounded-full mb-[18px]"
        style={{ background }}
      >
        <Icon size={24} strokeWidth={1.8} style={{ color: icon }} />
      </div>
      <p style={{ margin: "0 0 5px", fontSize: 16, fontWeight: 700, color: "#e5e6ea" }}>{heading}</p>
      <p
        style={{
          margin: "0 0 20px",
          fontSize: 13,
          color: "#6b7080",
          maxWidth: 340,
          lineHeight: 1.6,
        }}
      >
        {body}
      </p>
      {(primaryAction || secondaryAction) && (
        <div className="flex items-center gap-3">
          {secondaryAction && (
            <button
              onClick={secondaryAction.onClick}
              style={{
                padding: "9px 16px",
                borderRadius: 8,
                background: "#181a20",
                border: "1px solid #1c1e24",
                color: "#c3c5cc",
                fontSize: "12.5px",
              }}
            >
              {secondaryAction.label}
            </button>
          )}
          {primaryAction && (
            <button
              onClick={primaryAction.onClick}
              disabled={primaryAction.disabled}
              className="btn-cta inline-flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                padding: "9px 17px",
                borderRadius: 8,
                border: "none",
                color: "#fff",
                fontSize: "12.5px",
                fontWeight: 600,
              }}
            >
              {PrimaryIcon && <PrimaryIcon size={14} strokeWidth={2} />}
              {primaryAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
