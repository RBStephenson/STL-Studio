import { useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";

interface Props {
  value: string;
  options: string[];
  placeholder?: string;
  className?: string;
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
  onClick?: (e: React.MouseEvent) => void;
}

// Matches the list's max-h-48 (12rem) so the flip-up decision knows how much
// room the dropdown actually needs.
const DROPDOWN_MAX_HEIGHT = 192;

export function PartTypeCombo({ value, options, placeholder, className, onChange, onCommit, onClick }: Props) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The blur handler defers closing so a dropdown click lands first. Clear that
  // pending timer on unmount — otherwise a field blurred moments before its row
  // goes away calls setOpen on a dead component, which in jsdom means React
  // touching an already-torn-down window (STUDIO-348).
  useEffect(() => () => {
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
  }, []);

  const sorted = [...options].sort((a, b) => a.localeCompare(b));
  const filtered = value
    ? sorted.filter((o) => o.toLowerCase().includes(value.toLowerCase()))
    : sorted;

  const openDrop = () => {
    if (inputRef.current) setRect(inputRef.current.getBoundingClientRect());
    setOpen(true);
  };

  const pick = (opt: string) => {
    onChange(opt);
    onCommit(opt);
    setOpen(false);
  };

  // Prefer opening below the field (the common case); flip above it when
  // there isn't enough room below but there is above, so the list is never
  // clipped off the bottom of the viewport (e.g. a row near the page end).
  const spaceBelow = rect ? window.innerHeight - rect.bottom : 0;
  const openUpward = rect ? spaceBelow < DROPDOWN_MAX_HEIGHT && rect.top > spaceBelow : false;

  const dropdown =
    open && filtered.length > 0 && rect
      ? createPortal(
          <ul
            style={{
              position: "fixed",
              ...(openUpward
                ? { bottom: window.innerHeight - rect.top + 2 }
                : { top: rect.bottom + 2 }),
              left: rect.left,
              width: Math.max(rect.width, 140),
              zIndex: 9999,
            }}
            className="bg-gray-900 border border-gray-700 rounded shadow-xl max-h-48 overflow-y-auto"
          >
            {filtered.map((opt) => (
              <li
                key={opt}
                onMouseDown={(e) => { e.preventDefault(); pick(opt); }}
                className={`px-2 py-1 text-xs cursor-pointer hover:bg-indigo-900/50 ${opt === value ? "text-indigo-300 bg-indigo-950/40" : "text-gray-300"}`}
              >
                {opt}
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
        value={value}
        placeholder={placeholder}
        onClick={(e) => { e.stopPropagation(); onClick?.(e); openDrop(); }}
        onChange={(e) => onChange(e.target.value)}
        onFocus={openDrop}
        onBlur={() => {
          if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
          closeTimerRef.current = setTimeout(() => setOpen(false), 150);
          onCommit(value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setOpen(false);
        }}
        className={className}
      />
      {dropdown}
    </>
  );
}
