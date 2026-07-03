import { useState, useRef } from "react";
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

export function PartTypeCombo({ value, options, placeholder, className, onChange, onCommit, onClick }: Props) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = value
    ? options.filter((o) => o.toLowerCase().includes(value.toLowerCase()))
    : options;

  const openDrop = () => {
    if (inputRef.current) setRect(inputRef.current.getBoundingClientRect());
    setOpen(true);
  };

  const pick = (opt: string) => {
    onChange(opt);
    onCommit(opt);
    setOpen(false);
  };

  const dropdown =
    open && filtered.length > 0 && rect
      ? createPortal(
          <ul
            style={{ position: "fixed", top: rect.bottom + 2, left: rect.left, width: Math.max(rect.width, 140), zIndex: 9999 }}
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
        onBlur={() => { setTimeout(() => setOpen(false), 150); onCommit(value); }}
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
