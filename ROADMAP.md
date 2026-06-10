# Roadmap

This roadmap is organized by planned release milestone and mirrors the
[GitHub milestones](https://github.com/RBStephenson/STL-Inventory/milestones).
Items within a milestone are roughly ordered by priority, but exact sequencing
shifts as work progresses. Issues tagged
[`good first issue`](https://github.com/RBStephenson/STL-Inventory/issues?q=is%3Aopen+label%3A%22good+first+issue%22)
are a good starting point for new contributors.

---

## v0.5 — Library polish & scan reliability ✅ Complete

Core UX gaps and scan accuracy improvements, all merged to `main`: prev/next
navigation on model detail ([#101](https://github.com/RBStephenson/STL-Inventory/issues/101)),
thumbnail capture from the 3D viewer ([#100](https://github.com/RBStephenson/STL-Inventory/issues/100)),
manual force-group overrides ([#106](https://github.com/RBStephenson/STL-Inventory/issues/106),
[#107](https://github.com/RBStephenson/STL-Inventory/issues/107)),
stale-model pruning after full scans ([#53](https://github.com/RBStephenson/STL-Inventory/issues/53)),
and per-creator rescan bootstrap ([#50](https://github.com/RBStephenson/STL-Inventory/issues/50)).

---

## v0.5.1 — Release hardening ✅ Complete

Release-blocking bugs and security fixes from the June 2026 pre-release
full-project code review — all 17 issues closed. Highlights: blocked
cross-origin writes to the localhost API
([#213](https://github.com/RBStephenson/STL-Inventory/issues/213)),
fixed the standalone entry point drifting from `app.main`
([#212](https://github.com/RBStephenson/STL-Inventory/issues/212)),
cascade-deleted collection memberships
([#214](https://github.com/RBStephenson/STL-Inventory/issues/214)),
server-side storefront thumbnail downloads
([#208](https://github.com/RBStephenson/STL-Inventory/issues/208)),
and capped Cults3D scraper pagination
([#218](https://github.com/RBStephenson/STL-Inventory/issues/218)).

---

## v0.6 — Polish, bug fixes & painting groundwork 🚧 In progress

Mostly shipped. Landed so far: the painting module M0 groundwork — backend
package and DB tables ([#178](https://github.com/RBStephenson/STL-Inventory/issues/178),
[#179](https://github.com/RBStephenson/STL-Inventory/issues/179)), Settings
toggle and Guides / Paint Shelf route shells
([#180](https://github.com/RBStephenson/STL-Inventory/issues/180),
[#181](https://github.com/RBStephenson/STL-Inventory/issues/181)), and CI
wiring ([#182](https://github.com/RBStephenson/STL-Inventory/issues/182)) —
plus library exclude filters by creator and tag
([#204](https://github.com/RBStephenson/STL-Inventory/issues/204),
[#205](https://github.com/RBStephenson/STL-Inventory/issues/205)),
Loot Studios storefront enrichment
([#102](https://github.com/RBStephenson/STL-Inventory/issues/102)),
the image-update bug cluster ([#186](https://github.com/RBStephenson/STL-Inventory/issues/186),
[#189](https://github.com/RBStephenson/STL-Inventory/issues/189),
[#190](https://github.com/RBStephenson/STL-Inventory/issues/190),
[#203](https://github.com/RBStephenson/STL-Inventory/issues/203)),
database import ([#163](https://github.com/RBStephenson/STL-Inventory/issues/163)),
and a fullscreen lightbox ([#168](https://github.com/RBStephenson/STL-Inventory/issues/168)).

Remaining:

| Issue | Item |
|-------|------|
| [#32](https://github.com/RBStephenson/STL-Inventory/issues/32) | **Server-side persisted preferences** — NSFW default, page size, sort, filter presets (currently lost between browsers) |
| [#206](https://github.com/RBStephenson/STL-Inventory/issues/206) | **Exclude slicer project files from the scan** — and prune any already indexed |
| [#170](https://github.com/RBStephenson/STL-Inventory/issues/170) | **"Recently added" view** — highlight or filter models from the last scan |

---

## Painting M1 — Paint Shelf

Next up after v0.6. The painting module follows its own M0–M5 milestone track
from the [spec](docs/painting/spec.md) (see also the
[kickoff brief](docs/painting/kickoff.md)). M0 — the module wiring — shipped in
v0.6; M1 builds the Paint Shelf, the paint-inventory foundation the guide
work (M2+) stands on.

| Issue | Item |
|-------|------|
| [#240](https://github.com/RBStephenson/STL-Inventory/issues/240) | **Inventory data core** — `brand` / `paint_line` / `paint` models + CRUD endpoints, with the derived `matchable` flag |
| [#241](https://github.com/RBStephenson/STL-Inventory/issues/241) | **Paint Shelf table UI** — grid/filter/pagination reusing Library patterns, color chips from `paint.hex` |
| [#242](https://github.com/RBStephenson/STL-Inventory/issues/242) | **PaintRack CSV import with diff preview** — added/removed/changed, confirm-to-apply, never a blind overwrite |
| [#243](https://github.com/RBStephenson/STL-Inventory/issues/243) | **PaintRack CSV export** — lossless round-trip with the importer |
| [#244](https://github.com/RBStephenson/STL-Inventory/issues/244) | **Paint code validation** — per-line `code_pattern` checks on entry and import |

---

## v0.7 — Configuration, scan features & advanced UX

| Issue | Item |
|-------|------|
| [#31](https://github.com/RBStephenson/STL-Inventory/issues/31) | **Configurable scan rules** — ignore patterns, custom parts-folder names, toggle auto-tag inference |
| [#43](https://github.com/RBStephenson/STL-Inventory/issues/43) | **Adopt Alembic for DB migrations** — the hand-rolled `ALTER TABLE` startup loop only supports additive changes |
| [#164](https://github.com/RBStephenson/STL-Inventory/issues/164) | **Bulk actions** — tag, add to collection, or delete multiple models at once |
| [#165](https://github.com/RBStephenson/STL-Inventory/issues/165) | **Tag management UI** — rename, merge, and delete tags globally |
| [#172](https://github.com/RBStephenson/STL-Inventory/issues/172) | **Quick-assign tags/collections from the library card** — without opening the detail page |
| [#166](https://github.com/RBStephenson/STL-Inventory/issues/166) | **Print queue** — track per-model print status (queued, printing, printed) |
| [#167](https://github.com/RBStephenson/STL-Inventory/issues/167) | **Star ratings** — rate models 1–5 stars and filter by rating |
| [#169](https://github.com/RBStephenson/STL-Inventory/issues/169) | **Keyboard navigation** — j/k library browsing, `/` to focus search |
| [#220](https://github.com/RBStephenson/STL-Inventory/issues/220) | **Library search polish** — debounce input, stop flooding browser history |
| [#221](https://github.com/RBStephenson/STL-Inventory/issues/221) | **Frontend error-handling polish** — surface silent failures, replace `alert()` |
| [#219](https://github.com/RBStephenson/STL-Inventory/issues/219) | **download-zip hardening** — stream instead of building in memory; handle duplicate filenames |
| [#222](https://github.com/RBStephenson/STL-Inventory/issues/222) | **Auto-snapshot the database before restore/reset** |
| [#223](https://github.com/RBStephenson/STL-Inventory/issues/223) | **Scanner status polish** — completion summary message, consistent `_state_lock` use |
| [#224](https://github.com/RBStephenson/STL-Inventory/issues/224) | **Back-fill frontend test coverage** — Library filter state, ModelDetail navigation |

---

## Backlog (unscheduled)

Open issues not yet assigned to a milestone. Notable clusters:

**Variant group UX** — rename groups ([#183](https://github.com/RBStephenson/STL-Inventory/issues/183)),
quick inline rename ([#191](https://github.com/RBStephenson/STL-Inventory/issues/191)),
set the display thumbnail ([#193](https://github.com/RBStephenson/STL-Inventory/issues/193)),
assign one image to a whole group ([#184](https://github.com/RBStephenson/STL-Inventory/issues/184)),
clear a model's image ([#192](https://github.com/RBStephenson/STL-Inventory/issues/192)),
nested variant groups ([#188](https://github.com/RBStephenson/STL-Inventory/issues/188)),
image caching within a group ([#185](https://github.com/RBStephenson/STL-Inventory/issues/185)).

**Drag-to-group follow-ups** — merge two existing groups by dragging
([#136](https://github.com/RBStephenson/STL-Inventory/issues/136)),
multi-select drag ([#137](https://github.com/RBStephenson/STL-Inventory/issues/137)),
keyboard accessibility ([#139](https://github.com/RBStephenson/STL-Inventory/issues/139)).

**Infrastructure & code quality** — notarize the macOS binary
([#17](https://github.com/RBStephenson/STL-Inventory/issues/17)),
reload settings on `.env` change ([#140](https://github.com/RBStephenson/STL-Inventory/issues/140)),
`/scan/browse` directory allowlist ([#41](https://github.com/RBStephenson/STL-Inventory/issues/41)),
standardize DB session handling ([#45](https://github.com/RBStephenson/STL-Inventory/issues/45)),
dedupe tag-map logic ([#56](https://github.com/RBStephenson/STL-Inventory/issues/56)),
pre-tokenize matcher products ([#57](https://github.com/RBStephenson/STL-Inventory/issues/57)),
require branches up to date with `main` before merge
([#153](https://github.com/RBStephenson/STL-Inventory/issues/153)).

---

## Stretch goals

Large features that are well-defined but each represent a significant project.

| Issue | Item |
|-------|------|
| | **Painting module M2–M5** — guide data model + renderer + print view (M2), authoring + validation + PDF export (M3), AI drafts + color match (M4), full-corpus import (M5); see the [spec](docs/painting/spec.md) §15. Issues will be filed milestone by milestone as each phase starts |
| [#16](https://github.com/RBStephenson/STL-Inventory/issues/16) | **Cross-model kit building (kitbash)** — assemble a character from parts across multiple packs |
| [#29](https://github.com/RBStephenson/STL-Inventory/issues/29) | **Reorganize library on disk** — preview → apply with manifest/undo; standalone-only (Docker mounts are read-only) |

---

Have an idea or want to pick something up? Check the [open issues](https://github.com/RBStephenson/STL-Inventory/issues) or open a new one.
