import { useState } from "react";
import { Star } from "lucide-react";

interface Props {
  /** Current rating 1–5, or null when unrated. */
  value: number | null;
  /** Called with the new rating. Clicking the current rating again clears it (null). */
  onChange: (rating: number | null) => void;
  /** Star pixel size. */
  size?: number;
  /** Read-only display (no hover / click). */
  readOnly?: boolean;
  className?: string;
}

/**
 * 1–5 star rating control (#167). Hover previews the rating; clicking a star
 * sets it; clicking the currently-set star again clears the rating. The whole
 * widget stops click/preventDefault propagation so it can live inside a card
 * Link without navigating.
 */
export default function StarRating({ value, onChange, size = 16, readOnly = false, className = "" }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value ?? 0;

  return (
    <div
      className={`flex items-center ${className}`}
      onMouseLeave={() => setHover(null)}
      role="radiogroup"
      aria-label="Star rating"
    >
      {[1, 2, 3, 4, 5].map((star) => {
        const filled = star <= shown;
        return (
          <button
            key={star}
            type="button"
            disabled={readOnly}
            aria-label={`${star} star${star !== 1 ? "s" : ""}`}
            aria-checked={value === star}
            role="radio"
            onMouseEnter={readOnly ? undefined : () => setHover(star)}
            onClick={readOnly ? undefined : (e) => {
              e.preventDefault();
              e.stopPropagation();
              onChange(value === star ? null : star);
            }}
            className={`${readOnly ? "" : "cursor-pointer"} p-0.5 transition-colors ${
              filled ? "text-yellow-400" : "text-gray-600 hover:text-yellow-300"
            } disabled:cursor-default`}
          >
            <Star size={size} fill={filled ? "currentColor" : "none"} />
          </button>
        );
      })}
    </div>
  );
}
