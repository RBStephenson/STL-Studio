import { Link } from "react-router-dom";
import { HelpCircle } from "lucide-react";

interface Props {
  /** The id of the Help-page section to jump to, e.g. "kit-builder". */
  section: string;
  /** Tooltip / accessible label. */
  label?: string;
  className?: string;
}

/**
 * A small "?" button that deep-links into the relevant section of the in-app
 * Help page (`/help#<section>`). Drop it next to a screen's heading so users
 * can jump straight to the docs for what they're looking at.
 */
export default function HelpLink({ section, label = "How this works", className = "" }: Props) {
  return (
    <Link
      to={`/help#${section}`}
      title={label}
      aria-label={label}
      className={`text-gray-600 hover:text-indigo-400 transition-colors ${className}`}
    >
      <HelpCircle size={16} />
    </Link>
  );
}
