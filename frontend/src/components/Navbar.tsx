import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Box, FolderOpen, Users, LayoutGrid, EyeOff, Eye, AlertTriangle, Settings, Printer, HelpCircle, Paintbrush, Palette, Tag, Inbox } from "lucide-react";
import { useNSFW } from "../context/NSFWContext";
import { useAppSettings } from "../context/AppSettingsContext";
import { api } from "../api/client";

export default function Navbar() {
  const { pathname } = useLocation();
  const { showNSFW, toggle } = useNSFW();
  const { settings: appSettings } = useAppSettings();
  const [reviewCount, setReviewCount] = useState<number | null>(null);
  const [queueCount, setQueueCount] = useState<number | null>(null);

  useEffect(() => {
    api.models.stats().then(s => {
      setReviewCount(s.needs_review);
      setQueueCount(s.queued);
    }).catch(() => {});
  }, []);

  const links = [
    { to: "/",            label: "Library",     icon: LayoutGrid,    badge: null },
    { to: "/creators",    label: "Creators",    icon: Users,         badge: null },
    { to: "/collections", label: "Collections", icon: FolderOpen,    badge: null },
    { to: "/queue",       label: "Queue",       icon: Printer,       badge: queueCount },
    { to: "/triage",      label: "Triage",      icon: AlertTriangle, badge: reviewCount },
    { to: "/import",      label: "Import",      icon: Inbox,         badge: null },
    // Paint Shelf is standalone paint inventory — always available (#516).
    // Only Guides (and future AI) gate on the painting-guides flag.
    ...(appSettings.painting_guides_enabled ? [
      { to: "/painting/guides", label: "Guides", icon: Paintbrush, badge: null },
    ] : []),
    { to: "/painting/shelf", label: "Paint Shelf", icon: Palette, badge: null },
    { to: "/tags",       label: "Tags",        icon: Tag,           badge: null },
    { to: "/settings",   label: "Settings",    icon: Settings,      badge: null },
    { to: "/help",        label: "Help",        icon: HelpCircle,    badge: null },
  ];

  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-8 print:hidden">
      <Link to="/" className="flex items-center gap-2 text-indigo-400 font-bold text-lg shrink-0">
        <Box size={22} />
        STL Library
      </Link>

      <div className="flex items-center gap-1 ml-4">
        {links.map(({ to, label, icon: Icon, badge }) => (
          <Link
            key={to}
            to={to}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
              pathname === to
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-gray-100 hover:bg-gray-800"
            }`}
          >
            <Icon size={15} />
            {label}
            {badge != null && badge > 0 && (
              <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-xs font-medium leading-none ${
                pathname === to
                  ? "bg-white/20 text-white"
                  : "bg-yellow-500/20 text-yellow-400"
              }`}>
                {badge.toLocaleString()}
              </span>
            )}
          </Link>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={toggle}
          title={showNSFW ? "Hide NSFW content" : "Show NSFW content"}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors border ${
            showNSFW
              ? "bg-red-950/60 border-red-800 text-red-400 hover:bg-red-900/60"
              : "bg-gray-800 border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600"
          }`}
        >
          {showNSFW ? <Eye size={14} /> : <EyeOff size={14} />}
          {showNSFW ? "NSFW On" : "NSFW Off"}
        </button>
      </div>
    </nav>
  );
}
