# Handoff: STL Studio — Visual Refresh

## Overview
A refined visual/interaction pass over STL Studio (a local 3D-print-model library manager). Recreates every major screen from the existing React/Tailwind codebase (`frontend/`) in a tighter, more premium dark theme, and adds a few new interactive patterns (sidebar collapse, view-state switchers, sticky pagination).

## ⚠️ New Since Last Handoff
This package supersedes the previous drop. Same 20 screens, but with these additions layered in — implement these on top of anything already built from the prior version:

- **Complete Content/Loading/Empty/Error state coverage**: every screen with a state-view switcher now has all four states wired and rendered (previously several only had 2-3). Added **Empty** to Paint Shelf, Guide Reader, Variant Group. Added **Error** to Guides, Tags, Triage, Queue, Collections, Creators, Model Detail, Paint Shelf, Variant Group, Guide Reader (red-tinted dashed panel, `border:1px dashed rgba(244,63,94,.3)`, `background:#160c10`, alert-circle icon, heading + explanation + "Retry" CTA — matches the pre-existing pattern on Library/Import). Added **Loading** to Queue, Tags, Guides, Triage (shimmering skeletons using the shared `stl-shimmer` animation). When wiring to real data, map each pill state to query status: `content` → `isSuccess && data.length`, `loading` → `isPending`, `empty` → `isSuccess && !data.length`, `error` → `isError`.
- **Settings — reorganized navigation**: replaced the 6-tab horizontal underline nav with a left sidebar (210px rail, sticky) and consolidated to 5 groups: **General** (library page size, "New" badge window, NSFW toggle — moved out of the old grab-bag Preferences tab), **Library & Scanning** (folders, scan locations, reorganize tool, scan rules, tag rules — merges the old separate Library + Scanning tabs), **Features** (Painting Guides toggle + Image Gallery settings — replaces the old single-item Painting tab), **AI & Automation** (unchanged content, renamed from "AI & Integrations"), **Data** (unchanged). Sidebar items: `padding:9px 12px`, active state `background:#1c1e2e`, `border-left:2px solid #6366f1`, `border-radius:0 8px 8px 0`, text `#f4f4f6` active / `#8b8f9c` inactive. Recreate as a `settingsTab` state value driving both the active sidebar item and the rendered panel, same as before — just re-keyed (`general`/`library`/`features`/`ai`/`data`).
- **Guide Content Editor — sidebar tab nav for content spine**: the content-spine editor (left side of the 2-column layout) changed from a stacked-accordion list (all tabs expanded, all steps visible at once) to a 3-column layout: a narrow left sidebar (200px) listing spine tabs by name + step count (same active-state sidebar styling as Settings — `border-left:2px solid #6366f1`, `background:#1c1e2e` when active), a middle column showing only the **selected** tab's steps for editing, and the live preview sticky on the right (unchanged). Add an `activeSpineTab` (index) state to drive which tab's steps render in the middle column.

- **Focus-visible accessibility ring** (global, all screens): added
  ```css
  button:focus-visible, a:focus-visible, [role="button"]:focus-visible,
  [role="tab"]:focus-visible, .stl-chip:focus-visible, .stl-card:focus-visible {
    outline: 2px solid #6366f1; outline-offset: 2px; border-radius: 6px;
  }
  ```
  Covers every interactive primitive across the app: nav buttons, tab controls, filter/tag chips, and library/creator/collection cards. Recreate as a shared Tailwind utility (e.g. `focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 focus-visible:rounded-md`) applied wherever these primitives are rendered — not a one-off. Keyboard-only (mouse clicks should not show the ring), so keep it on `:focus-visible`, not `:focus`.

- **Guide Reader — Loading state** (new pill option next to existing Content/Empty switcher, top-right of the hero gradient): a full skeleton recreation of the reading view, still inside the same violet-to-dark gradient hero background:
  - Hero: 120×11px pill (category label), 60%-width×24px block (title), 75%-width×12px block (subtitle), 35%-width×11px block (byline) — all `rgba(255,255,255,.08)` (or `.06` for the lighter two), centered, `border-radius:4–6px`.
  - Paint-lines bar: 4 skeleton pill chips, 110×24px, `background:#1a1c22`, `border-radius:999px`, in the same flex row the real paint pills occupy.
  - Tabs row: 5 skeleton bars, 70×14px, `#1a1c22`, sitting on the same bottom-border divider as real tabs.
  - Value-map row: 4 columns, each a 44px-tall swatch block + a short label bar underneath, `#1a1c22`.
  - Step list: 3 skeleton step cards, each with a left border rule (`2px solid #1a1c22`) and stacked bars for step label/title/two description lines.
  - A single `stl-shimmer` sweep (`@keyframes stl-shimmer { 0%{translateX(-100%)} 100%{translateX(100%)} }`, 1.4s linear infinite, diagonal `100deg` gradient highlight) runs across the whole panel via one absolutely-positioned overlay div — not per-block — so the shine passes over hero, pills, tabs, chips, and steps together. Wire the pill switcher to real `isPending`/`isSuccess` query state; the skeleton block counts (4 pills, 5 tabs, 4 chips, 3 steps) are placeholders and can be dynamic once wired to data.

- **Guides (list) — Empty state** (new pill option alongside existing Content/Loading switcher): dashed-border panel replacing the card grid —
  - Container: `border:1px dashed #1e2027; border-radius:14px; background:#0e0f13; padding:64px 32px;`, centered column, text-center.
  - 56×56px circular icon badge, `background:#26163a`, containing a fuchsia (`#e879f9`) paint-brush/wand icon (stroke-width 1.6).
  - Heading "No painting guides yet" — 16px/700/`#e5e6ea`.
  - Body copy (13px/`#6b7080`, 1.6 line-height, max-width 320px): explains guides are step-by-step with paint swatches pulled from the shelf.
  - Primary CTA button ("New guide" or similar), same gradient-CTA treatment (`stl-cta` class: indigo gradient, lift+glow on hover) used elsewhere in the app.
  Wire to the real `data.length === 0` condition on the guides list query.

- **NSFW toggle badge** (nav bar, all content-bearing screens — Guide Reader, Guides, Help, Reorganize Library, Tags, etc.): outlined pill, right-aligned in the nav, `border:1px solid #202329; background:#181a20; color:#6b7080; font-size:13px; padding:7px 13px; border-radius:8px`, reading "NSFW Off". Should reflect and toggle the existing NSFW content-filter setting (already present in Settings/Preferences) — clicking it should flip state and label (e.g. "NSFW On" with an accent color) rather than being static chrome.

- **Triage — keyboard hint row** (bottom of the review card, below Back/Skip/Looks Good buttons): inline hint using a styled `<kbd>` element — `background:#1c1e26; border:1px solid #1c1e24; padding:2px 7px; border-radius:5px; font-family:monospace; font-size:11.5px; color:#dcdde2` — reading "→ / Space" followed by plain text "dismiss (looks fine)". Pattern should extend to the other keyboard shortcuts on this screen (Back/Skip) using the same `<kbd>` treatment for consistency, bound to the page's real keydown handlers.

Everything else (screens, layout, tokens, prior interaction notes below) is unchanged from the previous handoff.

## About the Design Files
The bundled file (`STL Library.dc.html`) is a **design reference built in HTML** — a single scrollable canvas containing every screen as a static/lightly-interactive mockup, created with inline styles and a small custom templating runtime (not React). It is **not production code** — do not copy its markup or "component" structure into the app. The task is to **recreate this visual design in the existing frontend codebase** (React + TypeScript + Tailwind CSS, using Vite), matching the codebase's existing patterns: functional components, Tailwind utility classes (not inline styles), the existing `api` client, TanStack Query hooks, and React Router.

## Fidelity
**High-fidelity.** Colors, spacing, typography, and copy are intended to be final. Treat exact hex values, radii, and spacing below as the target — translate them into Tailwind classes/theme extensions rather than eyeballing.

## Design System

### Colors (dark, indigo-accent — refined from the existing gray-950/indigo-600 palette)
- Page background: `#0b0c10`
- Panel/card background: `#131419` (secondary: `#141519`, `#0e0f13` for sidebars/inset panels)
- Borders: `#23252d` (subtle), `#1e2027` / `#262932` (dividers)
- Primary text: `#f4f4f6` / `#e5e6ea` / `#e9eaee`
- Secondary text: `#8b8f9c` / `#6b7080`
- Muted/tertiary text: `#5c6070` / `#4b4e58`
- Indigo accent: `#6366f1` → `#4f46e5` (gradient `135deg`), used for active states, primary CTAs, focus rings
- Status colors: amber `#fbbf24`/`#f59e0b` (needs review, warnings), yellow `#facc15` (favorites), sky `#7dd3fc`/`#38bdf8` (queued), emerald `#6ee7b7`/`#10b981` (printed/success), rose `#fda4af`/`#f43f5e` (destructive/NSFW), violet/fuchsia `#a78bfa`/`#e879f9` (AI features, painting guides)

### Typography
- Font: **Inter** (400/500/600/700/800), monospace for file paths/codes (system monospace stack)
- Page titles: 21–27px, weight 800, letter-spacing -0.01em
- Section labels: 11px, weight 700, uppercase, letter-spacing .04em, color `#5c6070`
- Body: 12.5–14px

### Shape & elevation
- Card radius: 10–13px; pill/chip radius: 999px (fully rounded)
- Page-frame shadow: `0 40px 80px -20px rgba(0,0,0,0.6)`
- Card hover: border color → `#4f46e5`, slight `translateY(-3px)` lift on Library cards

### Micro-interactions (apply globally)
- Primary gradient CTA buttons: on hover, `translateY(-1px)`, `brightness(1.08)`, `box-shadow: 0 8px 20px -6px rgba(79,70,229,.55)`; on active, `translateY(0)`, `brightness(0.96)`
- All inputs/selects/textareas: on focus, border → `#6366f1` + `box-shadow: 0 0 0 3px rgba(99,102,241,.15)`
- Card drag-grip handles: hidden by default, `opacity:1` on card hover

## Screens / Views
Each is a full recreation of the corresponding existing page component. Reference the live HTML file for exact layout/spacing per screen.

1. **Library** (`pages/Library.tsx` + `pages/library/*`) — Sidebar filter layout (new pattern, replaces the top filter bar): collapsible left rail (260px ↔ 64px icon rail, collapse state persisted to `localStorage`) with stat filter buttons, search, creator/site/support dropdowns, tag chips; main area has sort + Scan Library button, 5-col card grid, sticky bottom pagination bar (floating, blurred backdrop). Cards show drag-grip (variant grouping), badges (New/Review/variants), site tag, favorite/print-status hover icons. Content/Loading/Empty state switcher added for demo purposes — remove or wire to real query state.
2. **Model Detail** — Two-column: image + thumbnail strip + view toggle (Images/3D View) on the left; title, action row (Favorite/Rating/Print status/NSFW/Edit/Find on Web/Split pack/Merge group), variant switcher, stats, description, tags, collections, location on the right; full-width STL files table below. Content/Loading/Not-found state switcher.
3. **Settings** — Centered column, underline tab nav (Library/Scanning/Painting/AI & Integrations/Preferences/Data), fully wired tab switching. Library tab: add-folder form, layout preview, scan locations list, library tools. Other tabs per existing components.
4. **Creators** — Header with sort toggle (A–Z/Most models), search, Add Creator; 5-col card grid with per-card Rescan/Enrich actions. Content/Loading/Empty switcher.
5. **Collections** — 4-col grid, 4:3 cover cards (gradient cover vs. compact placeholder), hover actions (set cover/rename/delete), footer with name + model count. Content/Loading/Empty switcher.
6. **Print Queue** — Ordered grid with drag handles + position badges; dimmed "Recently Printed" section below with printed-date badges.
7. **Variant Group** — Rename-in-place header, bulk toolbar (Move/Set image/Set store page/Ungroup), 6-card grid with per-card Move/Set-image/Ungroup actions, "REP" badge on the group thumbnail.
8. **Import** — Folder path + Browse; phase switcher (Idle/Running/Done/Error) driving preview&import/quick-import buttons, spinner, success summary, error state.
9. **Import Preview** — Destination-library picker, "move imported packs" bar, expandable per-pack cards with enrich fields (creator/character/title, tags, source URL + Fetch).
10. **Triage (Review Queue)** — Progress bar, needs-review card (thumbnail + detected tags), Back/Skip/Looks Good actions, keyboard-hint row.
11. **Tags** — Filterable tag list, rename/merge/delete row actions (inline expand for rename and merge-into forms).
12. **Reorganize Library** — Template editor, color-coded stats bar, filter tabs, manifest rows with kind badges + collision/unclassifiable chips + expandable resolve-fields form.
13. **Help** — Sticky sidebar TOC (all real topic titles) + full content for 5 sections (Getting started, The Library, Model detail, Triage queue, About & support).
14. **Paint Shelf** — Header actions (Color match/Import/Export/Add paint), filter bar, paint table with color-swatch chips.
15. **Painting Guides** (list) — New guide/Import guide actions, 2-col card grid (title, draft/published badge, scale, franchise, tags).
16. **Guide Reader** — Gradient hero (category/title/subtitle/credit), paint-lines bar, tabs, value-map chips, step cards with paint swatches.
17. **Guide Editor** (metadata) — Title/title-lead/subtitle, scale/status/franchise selects, creator credit, removable tag chips.
18. **Guide Content Editor** — Validation chips, drag-reorderable spine editor (tabs→steps), sticky live-preview panel.
19. **AI Organize Review modal** — Violet-accented table (checkbox, file, current/proposed type & name, links-to), Cancel/Apply footer.
20. **Kit Builder modal** — 3D preview panel + part-group file lists with selection checkboxes, Copy list/Download zip footer.

## Interactions & Behavior
- **Sidebar collapse** (Library): toggle button flips between 260px and 64px width; state persists via `localStorage.getItem/setItem("stl_sidebar_collapsed")`.
- **Settings tabs**: click switches active tab + content panel (six tabs, one active at a time).
- **Content/Loading/Empty switchers** (Library, Creators, Collections; Loading/Not-found for Model Detail): three-way pill toggle swapping between real content, a shimmer skeleton grid (`@keyframes` translateX sweep, 1.4s loop), and an empty-state message. These were added to demonstrate states — wire to real query `isPending`/`isError`/`data.length === 0` conditions instead of local UI state.
- **Import phase switcher**: four-way pill (Idle/Running/Done/Error) swapping the panel content — mirror to the real `useState<Phase>` already in `ImportPage.tsx`.
- Hover states throughout: card border-color changes, drag-grip fade-in, button lift/glow (see Micro-interactions above).

## State Management
No real state management is needed from this handoff — it documents **visual/interaction targets** for state that already exists in the codebase (React Query hooks in `hooks/queries/*`, existing `useState` in each page). The only genuinely new pieces of UI state are:
- Sidebar collapsed boolean, persisted to `localStorage`.
- The demo-only view-state switchers (content/loading/empty) — replace with real query state when integrating.

## Design Tokens
See the Colors/Typography/Shape sections above — treat as candidate Tailwind theme extensions (e.g. add `bg-panel: #131419`, `border-subtle: #23252d` etc. to `tailwind.config.js` if adopting project-wide).

## Assets
No new image/icon assets — all icons are inline SVGs matching the existing `lucide-react` icon set already used in the codebase (same glyphs: Search, Star, Printer, Layers, etc.). Recreate with the existing `lucide-react` components rather than inline SVG.

## Screenshots
`screenshots/01-06.png` — reference captures of Guide Reader, Settings, Model Detail, Creators, Collections, and Library (sidebar layout).

## Files
- `STL Library.dc.html` — the full design reference (all 20 screens on one scrollable canvas, labeled via `data-screen-label` attributes for easy reference).
- `screenshots/` — PNG captures of key screens (see above).
