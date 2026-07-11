import { CSSProperties, ReactNode } from "react";

// Shared primitive for page-level loading skeletons (design/README.md
// "Complete Content/Loading/Empty/Error state coverage"). A skeleton screen
// is a relative container with one .stl-shimmer-overlay sweep (defined in
// index.css, introduced in STUDIO-131) plus one or more SkeletonBlock bars
// sized to the real content they stand in for.
export function SkeletonBlock({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div className={`rounded ${className}`} style={{ background: "#1a1c22", ...style }} />;
}

export function SkeletonPanel({
  className = "",
  style,
  children,
  "data-testid": dataTestId,
}: {
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
  "data-testid"?: string;
}) {
  return (
    <div className={`relative overflow-hidden ${className}`} style={style} data-testid={dataTestId}>
      <div className="stl-shimmer-overlay" />
      {children}
    </div>
  );
}
