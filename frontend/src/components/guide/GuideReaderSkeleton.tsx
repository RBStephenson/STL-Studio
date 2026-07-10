// Loading skeleton for GuideReaderPage (design/README.md "New Since Last
// Handoff" — Guide Reader loading state). Mirrors the real reader's hero /
// paint-bar / tabs / value-map / step-list layout so the shimmer sweep reads
// as a preview of the page about to appear, not a generic spinner.
const PILL_COUNT = 4;
const TAB_COUNT = 5;
const VALUE_MAP_COUNT = 4;
const STEP_COUNT = 3;

export default function GuideReaderSkeleton() {
  return (
    <div
      data-testid="guide-reader-skeleton"
      className="relative overflow-hidden rounded-b-2xl"
      style={{ background: "linear-gradient(135deg, #2f2360, #0b0c10)" }}
    >
      <div className="stl-shimmer-overlay" />

      {/* Hero */}
      <div className="flex flex-col items-center gap-3 px-4 pt-10 pb-8">
        <div className="h-[11px] w-[120px] rounded" style={{ background: "rgba(255,255,255,.08)" }} />
        <div className="h-6 w-3/5 rounded" style={{ background: "rgba(255,255,255,.08)" }} />
        <div className="h-3 w-3/4 rounded" style={{ background: "rgba(255,255,255,.06)" }} />
        <div className="h-[11px] w-[35%] rounded" style={{ background: "rgba(255,255,255,.06)" }} />
      </div>

      {/* Paint-lines bar */}
      <div className="flex flex-wrap justify-center gap-2 px-4 pb-6">
        {Array.from({ length: PILL_COUNT }).map((_, i) => (
          <div key={i} className="h-6 w-[110px] rounded-full" style={{ background: "#1a1c22" }} />
        ))}
      </div>

      <div className="max-w-5xl mx-auto px-4">
        {/* Tabs */}
        <div className="flex gap-4 border-b pb-3" style={{ borderColor: "rgba(255,255,255,.08)" }}>
          {Array.from({ length: TAB_COUNT }).map((_, i) => (
            <div key={i} className="h-3.5 w-[70px] rounded" style={{ background: "#1a1c22" }} />
          ))}
        </div>

        {/* Value-map row */}
        <div className="grid grid-cols-4 gap-3 py-6">
          {Array.from({ length: VALUE_MAP_COUNT }).map((_, i) => (
            <div key={i} className="flex flex-col gap-2">
              <div className="h-11 rounded" style={{ background: "#1a1c22" }} />
              <div className="h-2.5 w-2/3 rounded" style={{ background: "#1a1c22" }} />
            </div>
          ))}
        </div>

        {/* Step list */}
        <div className="flex flex-col gap-4 pb-10">
          {Array.from({ length: STEP_COUNT }).map((_, i) => (
            <div key={i} className="pl-4" style={{ borderLeft: "2px solid #1a1c22" }}>
              <div className="flex flex-col gap-2">
                <div className="h-2.5 w-16 rounded" style={{ background: "#1a1c22" }} />
                <div className="h-3.5 w-1/2 rounded" style={{ background: "#1a1c22" }} />
                <div className="h-2.5 w-full rounded" style={{ background: "#1a1c22" }} />
                <div className="h-2.5 w-4/5 rounded" style={{ background: "#1a1c22" }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
