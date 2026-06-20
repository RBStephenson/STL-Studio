import type { ReorganizeStats } from "../../api/client";

interface Props {
  stats: ReorganizeStats;
}

interface Stat {
  label: string;
  value: number;
  tone: "neutral" | "good" | "warn" | "bad";
}

const TONE_CLASS: Record<Stat["tone"], string> = {
  neutral: "bg-gray-800 border-gray-700 text-gray-200",
  good: "bg-green-950 border-green-800 text-green-300",
  warn: "bg-yellow-950 border-yellow-800 text-yellow-300",
  bad: "bg-orange-950 border-orange-800 text-orange-300",
};

/**
 * At-a-glance summary of a reorganize preview. Color-coded so a clean run reads
 * green while collisions/blockers stand out (#323).
 */
export default function ReorganizeStatsBar({ stats }: Props) {
  const items: Stat[] = [
    { label: "Total", value: stats.total, tone: "neutral" },
    { label: "Eligible", value: stats.eligible, tone: "good" },
    { label: "Moves", value: stats.moves_needed, tone: "neutral" },
    { label: "In place", value: stats.already_in_place, tone: "neutral" },
    { label: "Collisions", value: stats.collisions, tone: stats.collisions ? "warn" : "neutral" },
    { label: "Unclassifiable", value: stats.unclassifiable, tone: stats.unclassifiable ? "bad" : "neutral" },
    { label: "Blocked", value: stats.blocked, tone: stats.blocked ? "bad" : "neutral" },
  ];

  return (
    <div className="flex gap-2 flex-wrap" role="list" aria-label="Reorganize summary">
      {items.map((s) => (
        <div
          key={s.label}
          role="listitem"
          className={`px-3 py-1.5 rounded border text-sm ${TONE_CLASS[s.tone]}`}
        >
          <span className="font-semibold tabular-nums">{s.value}</span>{" "}
          <span className="text-xs opacity-80">{s.label}</span>
        </div>
      ))}
    </div>
  );
}
