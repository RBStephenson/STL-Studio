// Searchable picker for linking a sup (supported-version) file to its base —
// shared by StlFilesTable.tsx (horizontal layout) and StlFilesList.tsx
// (vertical layout). Type to filter by part name or filename; a plain
// <select> has no such filtering, which made picking the right file out of
// a long list tedious on kits with 50+ parts.
import { useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";

export interface FileLinkOption {
  id: number;
  label: string;      // part_name, falling back to filename when unset
  filename: string;    // always shown as a secondary hint, and searchable too
  disabled?: boolean;
  suffix?: string;     // " ✓ (already linked)" / " (linked to another)"
}

interface Props {
  options: FileLinkOption[];
  placeholder?: string;
  className?: string;
  onPick: (id: number) => void;
  onCancel: () => void;
}

// Matches the list's max-h-48 (12rem) so the flip-up decision knows how much
// room the dropdown actually needs — mirrors PartTypeCombo.
const DROPDOWN_MAX_HEIGHT = 192;

export function FileLinkCombo({ options, placeholder, className, onPick, onCancel }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(true);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Blur defers onCancel so a dropdown click lands first. Clear the pending
  // timer on unmount — onCancel updates parent state, so firing it after the
  // row is gone is a setState on a dead tree (STUDIO-348). Mirrors
  // PartTypeCombo.
  useEffect(() => () => {
    if (cancelTimerRef.current) clearTimeout(cancelTimerRef.current);
  }, []);

  const q = query.toLowerCase();
  const filtered = q
    ? options.filter((o) => o.label.toLowerCase().includes(q) || o.filename.toLowerCase().includes(q))
    : options;

  const openDrop = () => {
    if (inputRef.current) setRect(inputRef.current.getBoundingClientRect());
    setOpen(true);
  };

  const pick = (opt: FileLinkOption) => {
    if (opt.disabled) return;
    onPick(opt.id);
  };

  const spaceBelow = rect ? window.innerHeight - rect.bottom : 0;
  const openUpward = rect ? spaceBelow < DROPDOWN_MAX_HEIGHT && rect.top > spaceBelow : false;

  const dropdown =
    open && rect
      ? createPortal(
          <ul
            style={{
              position: "fixed",
              ...(openUpward
                ? { bottom: window.innerHeight - rect.top + 2 }
                : { top: rect.bottom + 2 }),
              left: rect.left,
              width: Math.max(rect.width, 220),
              zIndex: 9999,
            }}
            className="bg-gray-900 border border-gray-700 rounded shadow-xl max-h-48 overflow-y-auto"
          >
            {filtered.length === 0 && (
              <li className="px-2 py-1 text-xs text-gray-500">No matches</li>
            )}
            {filtered.map((opt) => (
              <li
                key={opt.id}
                onMouseDown={(e) => { e.preventDefault(); pick(opt); }}
                className={`px-2 py-1 text-xs ${
                  opt.disabled ? "text-gray-600 cursor-not-allowed" : "cursor-pointer hover:bg-indigo-900/50 text-gray-300"
                }`}
              >
                <div className="truncate">{opt.label}{opt.suffix}</div>
                {opt.label !== opt.filename && (
                  <div className="truncate text-[10px] text-gray-500 font-mono">{opt.filename}</div>
                )}
              </li>
            ))}
          </ul>,
          document.body
        )
      : null;

  return (
    <>
      <input
        ref={inputRef}
        autoFocus
        value={query}
        placeholder={placeholder}
        onClick={(e) => { e.stopPropagation(); openDrop(); }}
        onChange={(e) => { setQuery(e.target.value); openDrop(); }}
        onFocus={openDrop}
        onBlur={() => {
          if (cancelTimerRef.current) clearTimeout(cancelTimerRef.current);
          cancelTimerRef.current = setTimeout(onCancel, 150);
        }}
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
        className={className}
      />
      {dropdown}
    </>
  );
}
