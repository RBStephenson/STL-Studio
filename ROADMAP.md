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

## v0.6 — Polish, bug fixes & painting groundwork ✅ Complete

The painting module M0 groundwork — backend package and DB tables
([#178](https://github.com/RBStephenson/STL-Inventory/issues/178),
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
a fullscreen lightbox ([#168](https://github.com/RBStephenson/STL-Inventory/issues/168)),
server-side persisted preferences — NSFW default, page size, sort, and filter
presets ([#32](https://github.com/RBStephenson/STL-Inventory/issues/32)),
slicer project file exclusion from the scan with pruning of any already indexed
([#206](https://github.com/RBStephenson/STL-Inventory/issues/206)),
and the "Recently added" view with configurable day window and New badges
([#170](https://github.com/RBStephenson/STL-Inventory/issues/170)).

---

## v0.7 — Configuration, scan features & advanced UX ✅ Complete

The big interaction milestone, all merged: bulk actions
([#164](https://github.com/RBStephenson/STL-Inventory/issues/164)), global tag
management ([#165](https://github.com/RBStephenson/STL-Inventory/issues/165)),
quick-assign tags/collections from the card
([#172](https://github.com/RBStephenson/STL-Inventory/issues/172)), the print
queue with per-model status
([#166](https://github.com/RBStephenson/STL-Inventory/issues/166)), 1–5 star
ratings ([#167](https://github.com/RBStephenson/STL-Inventory/issues/167)),
full keyboard navigation
([#169](https://github.com/RBStephenson/STL-Inventory/issues/169)), a Library
sort control ([#247](https://github.com/RBStephenson/STL-Inventory/issues/247)),
search debounce ([#220](https://github.com/RBStephenson/STL-Inventory/issues/220)),
3D-viewer code-splitting ([#24](https://github.com/RBStephenson/STL-Inventory/issues/24)),
a `/scan/browse` allowlist ([#41](https://github.com/RBStephenson/STL-Inventory/issues/41)),
plus download-zip, snapshot-before-restore, scanner-status, and frontend
error-handling/test-coverage hardening
([#219](https://github.com/RBStephenson/STL-Inventory/issues/219),
[#222](https://github.com/RBStephenson/STL-Inventory/issues/222),
[#223](https://github.com/RBStephenson/STL-Inventory/issues/223),
[#221](https://github.com/RBStephenson/STL-Inventory/issues/221),
[#224](https://github.com/RBStephenson/STL-Inventory/issues/224)), and a batch
of reported bugs ([#285](https://github.com/RBStephenson/STL-Inventory/issues/285),
[#286](https://github.com/RBStephenson/STL-Inventory/issues/286),
[#287](https://github.com/RBStephenson/STL-Inventory/issues/287),
[#288](https://github.com/RBStephenson/STL-Inventory/issues/288)).

---

## v0.8 — Storefront, performance & painting guides ✅ Complete

Gumroad scraper overhaul — pagination beyond the first page
([#316](https://github.com/RBStephenson/STL-Inventory/issues/316)), the
`value=`/`content=` og-tag fix
([#317](https://github.com/RBStephenson/STL-Inventory/issues/317)), and richer
Inertia `data-page` JSON parsing
([#326](https://github.com/RBStephenson/STL-Inventory/issues/326)) — plus
external-drive access caching
([#304](https://github.com/RBStephenson/STL-Inventory/issues/304)), in-group
image caching ([#185](https://github.com/RBStephenson/STL-Inventory/issues/185)),
a `tag_sync` dedupe ([#56](https://github.com/RBStephenson/STL-Inventory/issues/56)),
and `.env` settings reload
([#140](https://github.com/RBStephenson/STL-Inventory/issues/140)). This
milestone also carried the painting **guide authoring** work: the
import/authoring UI ([#277](https://github.com/RBStephenson/STL-Inventory/issues/277)),
the structured tab→phase→step→swatch editor
([#329](https://github.com/RBStephenson/STL-Inventory/issues/329)), and Painting
M3 PDF export via Playwright
([#320](https://github.com/RBStephenson/STL-Inventory/issues/320)).

---

## v0.9 — Scan config, migrations & Library performance ✅ Complete

Released as **v0.9.0**. Shipped: configurable scan rules
([#31](https://github.com/RBStephenson/STL-Inventory/issues/31)), **Alembic**
migrations replacing the hand-rolled `ALTER TABLE` loop
([#43](https://github.com/RBStephenson/STL-Inventory/issues/43)), standardized
DB session handling ([#45](https://github.com/RBStephenson/STL-Inventory/issues/45)),
matcher pre-tokenization and dead-code cleanup
([#57](https://github.com/RBStephenson/STL-Inventory/issues/57),
[#353](https://github.com/RBStephenson/STL-Inventory/issues/353)), a Library
search clear button ([#355](https://github.com/RBStephenson/STL-Inventory/issues/355)),
revertible printed status ([#379](https://github.com/RBStephenson/STL-Inventory/issues/379)),
a scan-progress file-count fix
([#380](https://github.com/RBStephenson/STL-Inventory/issues/380)), and a
Library performance regression fix
([#382](https://github.com/RBStephenson/STL-Inventory/issues/382)).

The **Library reorganize / normalize-on-disk** epic was deferred to v0.10 to
ship v0.9.0 on the work above.

---

## v0.10 — Variant-group management 🚧 In progress

A focused milestone making variant groups fully manageable. Shipped: bulk
set-group endpoint + multi-select groundwork
([#374](https://github.com/RBStephenson/STL-Inventory/issues/374)), inline
rename ([#191](https://github.com/RBStephenson/STL-Inventory/issues/191)) and
group rename ([#183](https://github.com/RBStephenson/STL-Inventory/issues/183)),
set the display thumbnail
([#193](https://github.com/RBStephenson/STL-Inventory/issues/193)), assign one
image to a whole group ([#184](https://github.com/RBStephenson/STL-Inventory/issues/184)),
clear a model's image ([#192](https://github.com/RBStephenson/STL-Inventory/issues/192)),
drag-to-group **merge** ([#136](https://github.com/RBStephenson/STL-Inventory/issues/136))
and **multi-select drag**
([#137](https://github.com/RBStephenson/STL-Inventory/issues/137)) and
**keyboard accessibility** for the gesture
([#139](https://github.com/RBStephenson/STL-Inventory/issues/139)), in-group
Set-Thumbnail image-list caching
([#303](https://github.com/RBStephenson/STL-Inventory/issues/303)),
favorited/queued auto-promotion to the group rep
([#401](https://github.com/RBStephenson/STL-Inventory/issues/401), Phase 1 of
[#302](https://github.com/RBStephenson/STL-Inventory/issues/302)), and a Library
list-path performance pass — SQL variant collapse, page-scoped variant counts,
and supporting indexes
([#392](https://github.com/RBStephenson/STL-Inventory/issues/392),
[#393](https://github.com/RBStephenson/STL-Inventory/issues/393),
[#394](https://github.com/RBStephenson/STL-Inventory/issues/394)).

Still open:

| Issue | Item |
|-------|------|
| [#302](https://github.com/RBStephenson/STL-Inventory/issues/302) / [#399](https://github.com/RBStephenson/STL-Inventory/issues/399) | **Manual drag-to-reorder** models within a group (Phase 2; needs a persisted `variant_order` column) |
| [#188](https://github.com/RBStephenson/STL-Inventory/issues/188) | **Nested variant groups** — group variant groups (the largest remaining item) |
| [#29](https://github.com/RBStephenson/STL-Inventory/issues/29) | **Reorganize library on disk** (deferred from v0.9) — umbrella: preview → apply with manifest/undo |
| [#323](https://github.com/RBStephenson/STL-Inventory/issues/323) | **Reorganize Phase 1** — preview-only manifest |
| [#324](https://github.com/RBStephenson/STL-Inventory/issues/324) | **Reorganize Phase 2** — apply, undo, conflict resolution (2a/2b/2c) |

---

## v1.0 — Planned

| Issue | Item |
|-------|------|
| [#16](https://github.com/RBStephenson/STL-Inventory/issues/16) | **Cross-model kit building (kitbash)** — assemble a character from parts across multiple packs |
| [#17](https://github.com/RBStephenson/STL-Inventory/issues/17) | **Notarize the macOS standalone binary** |

---

## Painting module

The painting module follows its own M0–M5 track from the
[spec](docs/painting/spec.md) (see also the
[kickoff brief](docs/painting/kickoff.md)).

- **M0 — module wiring** ✅ — backend package, DB tables, Settings toggle, route
  shells, CI (shipped in v0.6).
- **M1 — Paint Shelf** ✅ — `brand`/`paint_line`/`paint` models + CRUD
  ([#240](https://github.com/RBStephenson/STL-Inventory/issues/240)), the shelf
  table UI ([#241](https://github.com/RBStephenson/STL-Inventory/issues/241)),
  PaintRack CSV import/export with diff preview
  ([#242](https://github.com/RBStephenson/STL-Inventory/issues/242),
  [#243](https://github.com/RBStephenson/STL-Inventory/issues/243)), and code
  validation ([#244](https://github.com/RBStephenson/STL-Inventory/issues/244)).
- **M2 — Guide model, renderer & print** ✅ — guide schema + CRUD, React reader,
  static-HTML exporter, HTML importer with round-trip, print view, and the
  model↔guide link.
- **M3 — Authoring, validation & PDF export** ✅ (delivered across v0.8) —
  import/authoring UI ([#277](https://github.com/RBStephenson/STL-Inventory/issues/277)),
  structured editor ([#329](https://github.com/RBStephenson/STL-Inventory/issues/329)),
  Playwright PDF export ([#320](https://github.com/RBStephenson/STL-Inventory/issues/320)).
- **M4 — AI drafts + color match** — generate guide drafts and match swatches to
  shelf paints (`generation.py` / `colormatch.py` are stubs today).
- **M5 — Full-corpus import** — bulk-import the reference guide corpus.

M4–M5 issues will be filed as each phase starts.

---

Have an idea or want to pick something up? Check the
[open issues](https://github.com/RBStephenson/STL-Inventory/issues) or open a new one.
