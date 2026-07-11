# STL Studio Redesign — Content / Loading / Empty / Not-Found / Error States

This is the explicit, per-screen spec for every non-happy-path state in the redesign. It exists because prior implementation passes have drifted from the reference file (`STL Library.dc.html`) — treat every value below (copy, hex, icon, spacing) as exact, not illustrative. Where a screen has a pill/state switcher in the reference file, click through it directly to see each state rendered; this doc transcribes what you'll see so you don't have to reverse-engineer it from screenshots.

## Shared visual pattern (applies to every Empty/Error state)

All empty and error states use the same container recipe — only the icon, copy, and CTA change:

```
padding: 64px 32px (72px 32px on a few screens — see per-screen notes)
border: 1px dashed <border-color>
border-radius: 14px
background: <bg-color>
text-align: center
display: flex; flex-direction: column; align-items: center; justify-content: center;
```

**Empty state container:** `border-color:#1e2027`, `background:#0e0f13`.
**Error state container:** `border-color:rgba(244,63,94,.3)`, `background:#160c10`.

**Icon badge** (both): 56×56px circle, centered, `margin-bottom:18px`, containing a 24×24 lucide-style stroke icon.
- Empty icon badge background is state-flavored: indigo-tint `#141726` (icon `#818cf8`) for neutral/structural empties, violet-tint `#26163a` (icon `#e879f9`) for painting-guide-flavored empties, sky-tint `#0c2233` (icon `#7dd3fc`) for queue, green-tint `#0f2417` (icon `#6ee7b7`) for "all caught up" triage.
- Error icon badge is always `background:rgba(244,63,94,.12)`, icon `stroke="#fda4af"`, an alert-circle glyph (circle + vertical line + dot), `stroke-width:1.8`.

**Heading:** `margin:0 0 5px; font-size:16px; font-weight:700; color:#e5e6ea;`
**Body copy:** `margin:0 0 20px; font-size:13px; color:#6b7080; max-width:320-340px; line-height:1.6;`
**Primary CTA** (gradient, "stl-cta" class): `padding:9px 17px; border-radius:8px; background:linear-gradient(135deg,#6366f1,#4f46e5); border:none; color:#fff; font-size:12.5px; font-weight:600;` — hover: `translateY(-1px)`, `brightness(1.08)`, `box-shadow:0 8px 20px -6px rgba(79,70,229,.55)`.
**Secondary/plain CTA** (used for "Clear filter", "Back to Library", "View details"): `padding:9px 16px; border-radius:8px; background:#181a20; border:1px solid #1c1e24; color:#c3c5cc; font-size:12.5px;` — no gradient, no lift.
Error CTA button label is always **"Retry"** unless noted otherwise below.

## Shared visual pattern — Loading (skeleton) states

- Card/grid skeletons: same-shape blocks as real content (`aspect-ratio:1` for square cards, matching border-radius), `background:#141519` (or `#131419` for text-line blocks), `border:1px solid #1a1b21`.
- One shimmer sweep per skeleton block (or one absolutely-positioned overlay for list/table skeletons): `position:absolute; inset:0; background:linear-gradient(100deg, transparent 30%, rgba(255,255,255,.03-.04) 50%, transparent 70%); animation: stl-shimmer 1.4s infinite;` — `pointer-events:none` when it's an overlay div spanning multiple rows.
- `@keyframes stl-shimmer { 0%{transform:translateX(-100%)} 100%{transform:translateX(100%)} }` — defined once, globally, in the page's `<style>` block.
- Text-line placeholders: flat `background:#1a1c22` or `#131419` bars, `border-radius:4px` (or `999px` for pill-shaped chip skeletons), no gradient of their own — they sit under the shared shimmer overlay.
- Skeleton counts are placeholders matching typical result-set size (see per-screen notes) — make them dynamic (matching real page-size) once wired to data.

---

## 1. Library (main grid)
State var: `viewState` (`content` / `loading` / `empty` / `error`) — demo-only pill switcher, top-right of toolbar.

- **Content:** 5-col card grid, real card markup (thumbnail, badges, name, creator, rating, kebab menu).
- **Loading:** same 5-col grid, each cell a `aspect-ratio:1` skeleton block (`#141519`, `border:1px solid #1a1b21`, `border-radius:13px`) with per-card shimmer overlay. 10 placeholder cards.
- **Empty:** icon = indigo search-circle (`stroke="#818cf8"`, magnifying glass). Heading **"No models found"**. Body: *"Nothing matches your current filters. Adjust your search, or scan your library folders for new models."* (max-width 340px). Two CTAs side by side: secondary **"Clear filters"** + gradient **"Scan library"** (with refresh icon).
- **Error:** icon = alert-circle. Heading **"Couldn't load your library"**. Body: *"The library index couldn't be read. It may be missing, corrupted, or on a drive that's currently unavailable."* Two CTAs: secondary **"View details"** + gradient **"Retry"** (with refresh icon). Padding `72px 32px` (not 64px) on this screen's empty/error.

*No Not-found state — a list screen has nothing to 404 on.*

## 2. Model Detail
State var: `detailView` (`content` / `loading` / `notfound` / `error`) — **no Empty**; a single model record either exists, is loading, 404s, or errors.

- **Content:** 2-col layout (image + thumbnails/left, title+actions+metadata/right), full-width STL files table below.
- **Loading:** left column = square skeleton image block with shimmer; right column = stacked text-line skeleton bars (title, stat rows, description lines) in matching shapes, no real copy.
- **Not found:** icon = indigo alert-circle (`stroke="#818cf8"` — note: indigo, not rose, since this isn't a failure, just absence). Heading **"Model not found"**. Body: *"It may have been removed, renamed, or excluded from the library."* Single secondary CTA **"Back to Library"** (no gradient CTA here — this is a dead end, not a retryable action). Padding `72px 32px`.
- **Error:** standard rose error pattern. Heading + body copy present but truncated in source at capture time — recreate using the shared error pattern (icon `#fda4af`, `background:#160c10`, `border:1px dashed rgba(244,63,94,.3)`) with a "Retry" CTA; confirm exact copy against the live pill switcher in the reference file if it differs from the shared template wording.

## 3. Settings
No state switcher — this screen is local form/tab UI over settings that always exist locally. No loading/empty/error to build (settings either exist with defaults or don't render at all).

## 4. Creators
State var: `creatorsView` (`content` / `loading` / `empty` / `error`).

- **Loading:** 5-col grid, `height:98px` skeleton rows (not square — creator cards are shorter), shimmer per card. 15 placeholders.
- **Empty:** icon = indigo people/users glyph. Heading **"No creators found"**. Body: *"Nothing matches your search or filters. Try a different term, or add a creator manually."* Single gradient CTA **"Add creator"** (plus icon).
- **Error:** Heading **"Couldn't load creators"**. (Body/CTA follow the shared error pattern — "Retry".)

## 5. Collections
State var: `collectionsView` (`content` / `loading` / `empty` / `error`).

- **Loading:** 4-col grid, `aspect-ratio:4/3` skeleton covers, shimmer per card. 8 placeholders.
- **Empty:** icon = indigo folder glyph. Heading **"No collections yet"**. Body: *"Group related models together — by project, army, or shelf — to keep your library organized."* Gradient CTA **"New collection"** (plus icon).
- **Error:** Heading **"Couldn't load collections"**. Body: *"Something went wrong loading your collections. Try again."* Gradient CTA **"Retry"** (no icon, plain label).

## 6. Print Queue
State var: `queueView` (`content` / `loading` / `empty` / `error`).

- **Loading:** 6-col grid, square skeleton thumbnails (`#141519`) + two text-line bars underneath (70%/45% width, flat `#131419`, no shimmer of their own — shimmer is on the image block only). 6 placeholders.
- **Empty:** icon = sky-tint badge (`background:#0c2233`, icon `stroke="#7dd3fc"`, inbox/tray glyph). Heading **"Your print queue is empty"**. Body: *"Add models from your library to line them up for printing."* Gradient CTA **"Browse library"** (back-arrow icon, label after icon).
- **Error:** Heading **"Couldn't load the print queue"**. Body: *"Something went wrong loading your queue. Try again."* Gradient **"Retry"**.

## 7. Variant Group
State var: `variantGroupView` (`content` / `loading` / `empty` / `error`).

- **Loading:** 6-col grid, square skeletons, shimmer, matches Queue's grid pattern. 6 placeholders.
- **Empty:** icon = indigo 4-square/grid glyph. Heading **"No variants in this group"**. Body: *"Move models into this group from the Library to start tracking them as variants."* Gradient CTA **"Go to Library"** (plain label, no icon).
- **Error:** Heading **"Couldn't load this variant group"**. Body: *"Something went wrong loading variants. Try again."* Gradient **"Retry"**.

## 8. Import
State var: `importPhase` (`idle` / `running` / `done` / `error`) — this is a **phase switcher**, not a content/loading/empty/error switcher; map directly to the existing `useState<Phase>` in `ImportPage.tsx`. No "empty" concept here.

- **Idle:** folder path input + Browse button + preview/quick-import actions.
- **Running:** spinner state (button becomes disabled/spinning — see reference for exact treatment).
- **Done:** success summary panel.
- **Error:** rose-tinted inline alert box (not the centered dashed-panel pattern used elsewhere) — `border:1px solid rgba(244,63,94,.3); background:rgba(244,63,94,.06); border-radius:10px; padding:14px 16px;`, alert-circle icon (`#fda4af`, 16px, `stroke-width:2`) top-left of a two-line text block: bold line **"Couldn't reach /import"** (`color:#fda4af; font-weight:600; font-size:13.5px`) + body *"The path doesn't exist, or STL Studio doesn't have permission to read it. Check the folder is spelled correctly and is accessible."* (`color:#fca5b5; font-size:12.5px; line-height:1.6`). Below the alert: the same path input + Browse row, plus a standalone gradient **"Try again"** button (not "Retry" — this screen uses different wording).

## 9. Import Preview
No state switcher in the reference — always shows populated per-pack cards. Build loading/empty/error only if/when wired to a real query; no spec exists yet for this screen's non-happy-path states — ask before inventing copy.

## 10. Triage (Review Queue)
State var: `triageView` (`content` / `loading` / `empty` / `error`).

- **Loading:** progress bar skeleton + stacked review-card skeleton (thumbnail block + text lines), shimmer overlay.
- **Empty ("all caught up" — this is a *good news* empty, not a dead end):** icon = green-tint badge (`background:#0f2417`, icon `stroke="#6ee7b7"`, checkmark glyph). Heading **"All caught up"**. Body: *"Nothing needs review right now. New scans will show up here for a quick check."* Secondary (non-gradient) CTA **"Scan library"**. Padding `72px 32px`.
- **Error:** Heading **"Couldn't load the review queue"**. Body: *"Something went wrong fetching models to review. Try again."* Gradient **"Retry"**.

## 11. Tags
State var: `tagsView` (`content` / `loading` / `empty` / `error`).

- **Loading:** stacked skeleton rows (`display:flex; flex-direction:column; gap:6px`), shimmer overlay across the whole list. 8 placeholder rows.
- **Empty (this one is a *filtered-to-nothing* empty, not a true empty library):** icon = indigo filter/funnel glyph. Heading **"No tags match "quick-print""** (dynamically interpolate the active filter term into the heading — shown here with an example term). Body: *"Try a different filter term, or clear it to see all tags."* Secondary (non-gradient) CTA **"Clear filter"**.
- **Error:** Heading **"Couldn't load tags"**. Body: *"Something went wrong reading your tag index. Try again."* Gradient **"Retry"**.

## 12. Reorganize Library
No state switcher — manifest rows render from local demo data only. No loading/empty/error spec exists; ask before inventing.

## 13. Help
No state switcher — static content, all 5 sections always present. No states to build.

## 14. Paint Shelf
State var: `paintShelfView` (`content` / `loading` / `empty` / `error`).

- **Loading:** table skeleton — real header row (`Color / Name / Brand / ...` labels, `#5c6070`, uppercase, 10.5px) stays visible; body rows are skeleton bars inside the same `#131419` panel with `border:1px solid #1a1b21; border-radius:12px`.
- **Empty:** icon = indigo paint-swatch/palette glyph (multiple dots). Heading **"No paints on your shelf yet"**. Body: *"Add paints manually or import a CSV so guides can reference colors you actually own."* Gradient CTA **"Add paint"** (plus icon) — infer label from the plus-icon pattern used elsewhere; confirm exact label text against the live switcher.
- **Error:** Heading **"Couldn't load the paint shelf"**. Body: *"Something went wrong loading your paints. Try again."* Gradient **"Retry"**.

## 15. Painting Guides (list)
State var: `guidesView` (`content` / `loading` / `empty` / `error`).

- **Loading:** 2-col grid, card-shaped skeletons (image block + two text lines), shimmer. 6 placeholders.
- **Empty:** icon = violet-tint badge (`background:#26163a`, icon `stroke="#e879f9"`, paint-brush/wand glyph). Heading **"No painting guides yet"**. Body: *"Write step-by-step guides for how you painted a model, with paint swatches pulled from your shelf."* Gradient CTA **"New guide"** (plus icon).
- **Error:** dashed rose panel (not full-bleed — this one sits inside the existing card-grid container area). Heading **"Couldn't load painting guides"**. Body: *"Something went wrong loading your guides. Try again."* Gradient **"Retry"**.

## 16. Guide Reader
State vars: `guideReaderView` drives **Content / Loading / Empty / Error** (four-way pill, top-right of the hero).

- **Content:** full gradient hero + paint-lines bar + tabs + value-map + step cards.
- **Loading:** full skeleton recreation *inside the same violet-to-dark gradient hero* (`linear-gradient(160deg,#241a3d,#0e0f13 70%)`) — hero title/subtitle/byline bars, 4 skeleton paint-pill chips, 5 skeleton tab bars, 4-column value-map skeleton, 3 skeleton step cards (each with `2px solid #1a1c22` left border + stacked bars). One shared shimmer overlay sweeps the whole panel (not per-block).
- **Empty (guide has no steps written yet):** icon = violet-tint badge (`#26163a` / `#e879f9`, paint-brush glyph — same icon as Guides-list empty). Heading **"This guide has no content yet"**. Body: *"Add tabs and steps in the content editor to start writing this painting guide."* Gradient CTA (icon+label — confirm label against reference; likely "Add content" or "Open editor").
- **Error:** Heading **"Couldn't load this guide"**. Body: *"Something went wrong loading the guide content. Try again."* Gradient **"Retry"**.

## 17. Guide Editor (metadata)
No state switcher — form always shows populated fields for the guide being edited. No states to build.

## 18. Guide Content Editor
No state switcher — spine editor operates on already-loaded guide data. No states to build.

## 19. AI Organize Review (modal)
No state switcher — modal only opens once results exist. No states to build.

## 20. Kit Builder (modal)
No state switcher — modal only opens once parts data exists. No states to build.

## 21. Color-Match Studio
Not in the original 20-screen list but present in the file — no state switcher; local tool UI. No states to build.

---

## Global accessibility rule (applies across every state above)
```css
button:focus-visible, a:focus-visible, [role="button"]:focus-visible,
[role="tab"]:focus-visible, .stl-chip:focus-visible, .stl-card:focus-visible {
  outline: 2px solid #6366f1; outline-offset: 2px; border-radius: 6px;
}
```
Every CTA/button rendered in an Empty or Error state must carry this focus ring. Keyboard-only — do not trigger on mouse click.

## Wiring checklist (per state, per screen)
| Pill | Maps to |
|---|---|
| `content` | `isSuccess && data.length` (or `isSuccess && !!data` for singular records) |
| `loading` | `isPending` |
| `empty` | `isSuccess && !data.length` (or filtered-to-zero for Tags/Creators search) |
| `notfound` | `isSuccess && !data` (Model Detail only) |
| `error` | `isError` |

## Screens confirmed to have NO loading/empty/error states (do not invent any)
Settings, Reorganize Library, Help, Guide Editor, Guide Content Editor, AI Organize Review, Kit Builder, Color-Match Studio, Import Preview (unspecified — ask first).
