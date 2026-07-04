// Prev / page-input / Next pagination control for the Library. The page input
// binds to local draft state so typing doesn't page on every keystroke — it
// commits on blur or Enter, clamped to [1, totalPages]. Extracted from
// Library.tsx (STUDIO-63 P4) — behavior-preserving.

import { useState, useEffect } from "react";

interface PaginationBarProps {
  page: number;
  totalPages: number;
  onPage: (p: number) => void;
  className?: string;
}

export default function PaginationBar({ page, totalPages, onPage, className = "mt-8" }: PaginationBarProps) {
  const [draft, setDraft] = useState(String(page));

  useEffect(() => { setDraft(String(page)); }, [page]);

  const btnCls = "px-3 py-1.5 rounded bg-gray-900 border border-gray-700 text-sm disabled:opacity-40 hover:border-gray-500 transition-colors";

  function commit(raw: string) {
    const n = parseInt(raw, 10);
    if (!isNaN(n)) onPage(Math.min(totalPages, Math.max(1, n)));
  }

  return (
    <div className={`flex items-center justify-center gap-2 ${className}`}>
      <button onClick={() => onPage(page - 1)} disabled={page === 1} className={btnCls}>Prev</button>
      <div className="flex items-center gap-1.5 text-sm text-gray-400">
        <input
          type="text"
          inputMode="numeric"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => { if (e.key === "Enter") { commit(draft); (e.target as HTMLInputElement).blur(); } }}
          className="w-12 text-center rounded bg-gray-900 border border-gray-600 py-1 text-sm text-white focus:outline-none focus:border-indigo-500"
        />
        <span>/ {totalPages}</span>
      </div>
      <button onClick={() => onPage(page + 1)} disabled={page === totalPages} className={btnCls}>Next</button>
    </div>
  );
}
