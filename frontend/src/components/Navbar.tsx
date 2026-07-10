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

  // Refetch the badge counts on every route change, when the tab regains
  // focus, and on a short poll, so they don't go stale after a same-page
  // mutation elsewhere (e.g. a bulk-enrich flag or manual "flag for review"
  // that never triggers a route change or window blur/refocus) (STUDIO-6).
  useEffect(() => {
    let alive = true;
    const refresh = () => {
      api.models.stats().then(s => {
        if (!alive) return;
        setReviewCount(s.needs_review);
        setQueueCount(s.queued);
      }).catch(() => {});
    };
    refresh();
    window.addEventListener("focus", refresh);
    const poll = window.setInterval(refresh, 15000);
    return () => { alive = false; window.removeEventListener("focus", refresh); window.clearInterval(poll); };
  }, [pathname]);

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
        STL Studio
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
          className="flex items-center gap-1.5 text-[13px] px-[13px] py-[7px] rounded-lg border transition-colors"
          style={
            showNSFW
              ? { borderColor: "var(--color-status-rose-dark)", background: "rgba(244,63,94,.12)", color: "var(--color-status-rose)" }
              : { borderColor: "#202329", background: "#181a20", color: "var(--color-text-secondary-alt)" }
          }
        >
          {showNSFW ? <Eye size={14} /> : <EyeOff size={14} />}
          {showNSFW ? "NSFW On" : "NSFW Off"}
        </button>
      </div>
    </nav>
  );
}
