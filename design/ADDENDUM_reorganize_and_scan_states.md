# Addendum: Reorganize Library trigger + scan states

Supersedes nothing — this is additive to the main README/STATES.md. Scope: moving
the Reorganize Library entry point out of Settings, and adding explicit
scan/idle/error states to three places. Reference the updated
`STL Library.dc.html` in this folder (`data-screen-label="Creators"`,
`data-screen-label="Reorganize Library"`, `data-screen-label="Settings"` →
Library & Scanning tab).

## 1. Moved "Reorganize Library" out of Settings

**Problem it fixes:** the old Settings → Library & Scanning tab had an "Enable
Reorganize Library" checkbox that acted as both a feature flag *and* the only
way to reach the tool — a maintenance action stranded as a settings toggle.

**Change:**
- Kept `reorganize_enabled` in `pages/settings/LibraryTab.tsx` as a pure
  feature flag (see §5a below) — it no longer renders a `<Link
  to="/reorganize">` itself.
- Added a **"Library Tools"** dropdown button to the Creators screen's toolbar
  (top of `pages/Creators.tsx`, next to the existing "Refresh enrich"
  button) containing:
  - **Reorganize Library** → navigates to `/reorganize`
  - **Rescan All Folders** → stub for now, same visual slot
- `reorganize_enabled` should still gate whether "Reorganize Library" appears
  in this menu (same flag, same default-off behavior) — just don't gate it
  behind Settings navigation only. If the flag is off, either hide the menu
  item or hide the whole "Library Tools" button (designer's call, not
  specified further here — ask if it matters).
- Note the Creators screen was picked as the toolbar host only because this
  design file doesn't include a main Library grid screen — **if
  `pages/Library.tsx` has a top toolbar in the real app (it does), put
  "Library Tools" there instead,** since that's the more natural home. Keep it
  on Creators too only if that seems useful; otherwise one location is enough.

**Dropdown visual spec:** trigger button matches existing toolbar button style
(`#181a20` bg, `#1c1e24` border, `#c3c5cc` text, 8px radius). Panel: 220px wide,
`#15161b` bg, `#23252d` border, 10px radius, positioned `top: calc(100% + 6px)`,
row hover `#1e2028`.

## 2. Reorganize Library: no longer auto-scans on mount

**Problem it fixes:** `ReorganizePage.tsx` currently calls
`api.reorganize.preview(template)` automatically in a `useEffect` on mount (see
`DEBOUNCE_MS` effect, ~line 92). Scanning/building a plan should be a
deliberate, user-triggered action, not something that fires the instant the
page loads.

**Change — three states, matching the existing `useScanStatus` /
`ScanButton.tsx` pattern already used elsewhere in the app (`pages/Library.tsx`
uses this for the library scan):**

- **Idle (default on page load):** template editor is visible and editable,
  but no preview fetch happens yet. Below it, an empty-state panel: dashed
  border (`#1e2027`), circular icon badge, "No plan yet", explanatory copy,
  and a primary gradient CTA **"Build Reorganize Plan"** (reuses `stl-cta`
  gradient button style). Clicking it triggers the first `preview()` call.
- **Scanning:** replace the idle panel with a banner (`#131926` bg,
  `#1e2b45` border, spinner icon, "Building reorganize plan…" + explanatory
  line, progress bar) and a **Cancel** button (square icon, same style as
  `ScanButton`'s cancel state). Should call whatever cancel/abort mechanism
  the real preview request supports; if the backend call can't be aborted
  mid-flight, at minimum stop showing the scanning UI and return to idle.
- **Content (existing table):** unchanged manifest/stats/tabs UI, plus a small
  **"Rebuild Plan"** button (top-right, ghost style) that re-triggers the scan
  — this replaces automatic re-fetching on template/override changes if you
  want the same "explicit trigger" principle applied throughout, though the
  existing debounced re-fetch-on-edit behavior (`DEBOUNCE_MS` effect) is
  reasonable to keep as-is for override edits within an existing plan. Use
  your judgment / ask if unsure which parts should stay automatic.
- **Error:** rose/red dashed panel (matches the Guides/Tags/etc. error
  pattern already documented in STATES.md — `border:1px dashed
  rgba(244,63,94,.3)`, `background:#160c10`, alert-circle icon, "Couldn't
  build the plan", explanatory copy, **Retry** CTA that re-runs the scan).

Map to real data: `idle` → no request made yet, `scanning` → request in
flight, `content` → resolved successfully, `error` → request rejected. This is
a structural change to `ReorganizePage.tsx`'s existing `loading`/`error`
local state, not new infra.

## 3. Settings → Library & Scanning tab: added a scan state

Independent of the Reorganize move above — the "Add a Folder" / "Scan
Locations" tab itself can also be mid-scan (e.g. after "Rescan All Folders").
Added a small Content/Scanning switcher at the top-right of the tab; Scanning
shows the same banner treatment as above, and dims + disables (`opacity:.45;
pointer-events:none`) the folder list/tools underneath while active. Wire to
whatever scan-status polling already backs `useScanStatus` — this should be
the same underlying scan job as the Library screen's "Scan Library" button.

## 4. Creators screen: per-card Rescan now shows a scanning state

Each creator card's existing "Rescan" button now disables itself and swaps its
label/icon to a spinning "Scanning…" while that creator's rescan is running,
instead of no-op/immediate-return. Reuse `useScanStatus`-style
running/disabled state, scoped per creator id rather than global.

## 5a. "Enable Reorganize Library" flag — kept, re-scoped

The old checkbox (`reorganize_enabled`) is **back** in Settings → Library &
Scanning, same field, same default-off behavior — but it no longer doubles as
the launch point. It now purely gates whether the **"Reorganize Library"**
row appears inside the "Library Tools" dropdown (item 1 above). "Rescan All
Folders" in that same menu is unaffected by this flag. Copy under the
checkbox: "Off by default. When on, 'Reorganize Library' appears in the
Library Tools menu (Creators toolbar)." Implementation is just the existing
`settings.reorganize_enabled` conditional, moved from wrapping a `<Link>` in
`LibraryTab.tsx` to wrapping the menu item's render.

## 6. Reorganize Library: paginated results table

**Problem it fixes:** the plan table rendered every proposed move/rename/skip
in one long unpaginated list — unusable on large libraries (hundreds to
thousands of entries).

**Change (see updated `data-screen-label="Reorganize Library"` in
`STL Library.dc.html`, `reorgEntries`/`reorgTabs` logic):**
- Category tabs (**All / Moves / Collisions / Unclassifiable / Blocked /
  Already In Place**) are now clickable filters over the full result set —
  not just a visual label row. Switching tabs resets to page 1.
- Results are paginated at a **page-size selector: 20 / 50 / 100 per page**
  (segmented control, same style as the state switcher — active pill
  `#4f46e5`/white, inactive `#181a20`/`#c3c5cc`). Default 20. Changing page
  size resets to page 1.
- Footer row below the table: left side "Showing X–Y of N" (count reflects
  the *currently filtered* tab, not the whole plan); right side Prev/Next
  buttons (disabled + dimmed at the ends) plus numbered page buttons with
  ellipsis collapsing for large page counts (always show first, last, and ±1
  around current page).
- Real implementation should paginate/filter server-side once plan size is
  non-trivial (the mock filters/slices an in-memory array since this is a
  static prototype) — i.e. `api.reorganize.preview()` should accept
  `tab`/`category`, `page`, `pageSize` params and return a total count,
  rather than shipping the whole plan to the client.
- Apply what's mentioned in item 2 above about keeping "Rebuild Plan"
  explicit — rebuilding should reset to tab "All", page 1, and whatever page
  size was last selected.

## 8. Library screen: variant group side panel

**Change:** clicking a card badged "N variants" on the Library grid no longer
navigates away. Instead a docked right-side panel (in-flow flex child, width
animates 0→380px, not an overlay) slides open showing that group's variants
as **list rows** (56px thumbnail left, variant name + file-size/type on the
right, REP badge on the thumbnail, overflow-menu affordance), with a close
(×) button and an "Open full view" link to the existing Variant Group screen
for full editing.

**As built (STUDIO-350)** — where the implementation deliberately diverges
from this mock:

- **State lives in the URL, not the component.** `/?group=<variant_group_id>`,
  so browser Back closes the panel, the view is deep-linkable, and a reload
  restores it. The mock's `variantSidebarGroupName` local state would have
  broken all three — and the desktop shell wires mouse Back/Forward buttons
  to browser history, so Back-to-dismiss is a reflex users will have.
- **Keyed by `variant_group_id`, not name.** Group labels are neither unique
  nor stable; `modelLinkTo` already appends `?gid=` for exactly this reason.
  Cards from before durable groups carry no id, so they keep navigating to
  the full page rather than opening the panel.
- **Rows show tags, not file size/type.** `GET /models/variants` returns
  neither a size nor an STL count (`size_bytes` lives on the per-file type,
  not the model), so the mock's "4.2 MB · STL" is not obtainable without a
  backend aggregate. Rows show the model's tags instead, styled exactly as
  the Library card styles them, with a `+N` overflow.
- **The panel is resizable**, 300px to `min(720px, 45% of window)`, persisted
  in `localStorage`. The upper bound is not arbitrary: the model grid's
  Tailwind breakpoints measure the viewport, so an unbounded panel starves
  the grid into 100px cards. Row thumbnails, chip count and title size step
  up with the panel's own width.
- **Content states** the mock does not define: loading skeleton, error with
  retry, and empty.
- **The per-row overflow (⋯) affordance is not implemented** — the mock shows
  the control but defines no menu, and a control that does nothing is worse
  than none. Pending a decision on its contents.
- Behind `variant_sidebar_enabled`, default off. With the flag off the
  Library behaves exactly as before.

## 7. Library Tools moved from Creators to Library toolbar

**Change:** the "Library Tools" dropdown (Reorganize Library, Rescan All
Folders) previously lived in the Creators tab toolbar. It's library-wide,
not creator-specific, so it now lives in the main **Library** screen's
toolbar (the id="1b" wireframe section), next to the content-state switcher.
Same `toggleLibraryTools`/`libraryToolsOpen`/`goReorganize` state and markup,
just relocated. No longer present in Creators.

## 5b. Toast on scan completion

Added a lightweight toast (bottom-center, auto-dismiss ~3s, `#15161b` panel,
green checkmark) that fires when any of the following complete successfully:
per-creator rescan ("Rescanned {name}."), Reorganize plan build ("Reorganize
plan ready."), and the Library & Scanning tab scan ("Scan complete."). If the
app already has a toast/notification system (check for a `ToastContext` or
similar — `useScanStatus.ts` references `useToast()` from
`context/ToastContext`), **use that existing system instead of building a new
one** — this mockup's toast is a stand-in for whatever `toast(message,
"success")` call is already wired through `useScanStatus`.
