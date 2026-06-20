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

## v0.10 — Painting depth 🚧 In progress

| Issue | Item |
|-------|------|
| [#339](https://github.com/RBStephenson/STL-Inventory/issues/339) | **Paint mixes as swatches** — true mix modelling: nullable paint_id, ratios, round-trip, blended chip |
| [#271](https://github.com/RBStephenson/STL-Inventory/issues/271) | **Painting round-trip coverage gaps** — step 3: byte-fidelity for series-badge filenames, skills-tab bodies, and `GUIDE_THINNING` literal |

Already landed since v0.9.0: drag-and-drop HTML guide import
([#413](https://github.com/RBStephenson/STL-Inventory/issues/413)), guide-import
paint resolution UI ([#417](https://github.com/RBStephenson/STL-Inventory/issues/417)
— map/force-add/skip unresolved paints before committing), inline tag editing on
model detail ([#411](https://github.com/RBStephenson/STL-Inventory/issues/411)), and
hide-printed filter with variant grouping preserved.

> The variant-group management cluster originally tracked under v0.10 (rename,
> merge, drag-to-group + keyboard a11y, display thumbnail, image-list caching,
> rep auto-promotion, and manual drag-to-reorder — #136/#137/#139/#183/#184/#191/
> #192/#193/#302/#303/#374/#399) all landed on `main` ahead of the **v0.9.0** cut,
> so it shipped as part of that release. Nested groups-within-groups
> ([#188](https://github.com/RBStephenson/STL-Inventory/issues/188)) was closed as
> out of scope — group merging already covers combining groups.

---

## v0.11 — Library reorganize ✅ Complete

The opt-in, preview-first **reorganize / normalize-on-disk** epic (standalone-only —
Docker mounts are read-only). Built against a persisted, identified manifest so the
apply step executes and verifies the *approved* plan rather than blindly recomputing.
Shipped in **v0.11.0**.

| Issue | Item |
|-------|------|
| [#29](https://github.com/RBStephenson/STL-Inventory/issues/29) | **Reorganize / normalize the library on disk** — umbrella: preview → resolve → apply with undo |
| [#323](https://github.com/RBStephenson/STL-Inventory/issues/323) | **Phase 1 — preview manifest** ([#426](https://github.com/RBStephenson/STL-Inventory/pull/426)) — per-file move sets, real `(size, mtime)` fingerprints, sanitization/collision/escape/override-reference flags; no files moved |
| [#324](https://github.com/RBStephenson/STL-Inventory/issues/324) | **Phase 2 — apply, undo, resolution** — 2a apply ([#431](https://github.com/RBStephenson/STL-Inventory/pull/431): drift abort, EXDEV-safe move, crash-safe undo log, scan-root confinement), 2b undo ([#432](https://github.com/RBStephenson/STL-Inventory/pull/432): idempotent reverse with verify-before-revert), 2c resolution + wired apply/undo UI ([#433](https://github.com/RBStephenson/STL-Inventory/pull/433)) |

---

## v0.12 — Import-and-organize pipeline — Planned

The end-to-end **import → enrich → organize** workflow for loose, badly-named, or
unknown-creator files. Reorganize (v0.11) is only the last mile; these add the
import and bulk-enrich steps that make unorganized files eligible to file away.
Both children reuse the v0.11 Phase 2 apply/move engine, so this milestone
sequences behind [#324](https://github.com/RBStephenson/STL-Inventory/issues/324).

| Issue | Item |
|-------|------|
| [#427](https://github.com/RBStephenson/STL-Inventory/issues/427) | **Epic — import-and-organize pipeline** for loose/unknown files |
| [#428](https://github.com/RBStephenson/STL-Inventory/issues/428) | **Child A — one-shot import folder → library** (move-in ingest, not a permanent scan root) |
| [#429](https://github.com/RBStephenson/STL-Inventory/issues/429) | **Child B — bulk-enrich metadata** (set creator/character/title across a selection — the bridge to reorganize-eligibility) |

---

## v1.0 — Planned

| Issue | Item |
|-------|------|
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
- **M5 — Full-corpus import** — bulk-import the reference guide corpus. Includes the
  remaining round-trip gaps tracked under [#271](https://github.com/RBStephenson/STL-Inventory/issues/271).

M4–M5 issues will be filed as each phase starts.

---

## Stretch goals / backlog

Larger, well-defined efforts not tied to a near-term milestone.

| Issue | Item |
|-------|------|
| [#16](https://github.com/RBStephenson/STL-Inventory/issues/16) | **Cross-model kit building (kitbash)** — assemble a character from parts across multiple packs; needs cross-model part-picker UI design |

---

Have an idea or want to pick something up? Check the
[open issues](https://github.com/RBStephenson/STL-Inventory/issues) or open a new one.
