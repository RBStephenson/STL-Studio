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

## v0.10 — Painting depth & variant-group management ✅ Complete

Released as **v0.10.0**. Painting depth: paint mixes as first-class swatches
([#339](https://github.com/RBStephenson/STL-Inventory/issues/339)), guide-import
paint resolution — map/force-add/skip unresolved paints before committing
([#417](https://github.com/RBStephenson/STL-Inventory/issues/417)),
drag-and-drop HTML guide import
([#413](https://github.com/RBStephenson/STL-Inventory/issues/413)), and a dark,
readable print/PDF guide stylesheet
([#418](https://github.com/RBStephenson/STL-Inventory/issues/418)).

The **variant-group management** cluster also landed in full: rename groups
([#183](https://github.com/RBStephenson/STL-Inventory/issues/183)), one image for
a whole group ([#184](https://github.com/RBStephenson/STL-Inventory/issues/184)),
inline rename ([#191](https://github.com/RBStephenson/STL-Inventory/issues/191)),
quick clear-image ([#192](https://github.com/RBStephenson/STL-Inventory/issues/192)),
pick the display thumbnail
([#193](https://github.com/RBStephenson/STL-Inventory/issues/193)), drag-to-group
merge / multi-select / keyboard accessibility
([#136](https://github.com/RBStephenson/STL-Inventory/issues/136),
[#137](https://github.com/RBStephenson/STL-Inventory/issues/137),
[#139](https://github.com/RBStephenson/STL-Inventory/issues/139)), the bulk
set-group endpoint ([#374](https://github.com/RBStephenson/STL-Inventory/issues/374)),
manual within-group ordering + rep auto-promotion
([#302](https://github.com/RBStephenson/STL-Inventory/issues/302),
[#399](https://github.com/RBStephenson/STL-Inventory/issues/399),
[#401](https://github.com/RBStephenson/STL-Inventory/issues/401)), and in-group
image caching ([#303](https://github.com/RBStephenson/STL-Inventory/issues/303)) —
plus inline tag editing on model detail
([#411](https://github.com/RBStephenson/STL-Inventory/issues/411)) and
variant-collapse / default-sort performance work
([#392](https://github.com/RBStephenson/STL-Inventory/issues/392),
[#393](https://github.com/RBStephenson/STL-Inventory/issues/393),
[#394](https://github.com/RBStephenson/STL-Inventory/issues/394)).
Nested groups-within-groups
([#188](https://github.com/RBStephenson/STL-Inventory/issues/188)) was closed as
out of scope — group merging already covers combining groups.

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

## v0.12 — Import-and-organize pipeline ✅ Complete

The end-to-end **import → enrich → organize** workflow for loose, badly-named, or
unknown-creator files. Reorganize (v0.11) is only the last mile; these add the
import and bulk-enrich steps that make unorganized files eligible to file away.
All of it reuses the v0.11 Phase 2 apply/move engine — no second mover.

Shipped in **v0.12.0**.

The epic (#427) landed the building blocks — one-shot inbox import and
bulk-enrich — plus the Import Preview **foundation**: named libraries with a
source→library mapping, the pack-grouped preview projection, and stage + batch
apply through the reorganize engine. The browse-first **Import Preview screen**
itself (#449) completed in **v0.13** (below).

| Issue | Item |
|-------|------|
| [#427](https://github.com/RBStephenson/STL-Inventory/issues/427) | **Epic — import-and-organize building blocks** for loose/unknown files |
| [#428](https://github.com/RBStephenson/STL-Inventory/issues/428) | **One-shot import folder → library** ([#446](https://github.com/RBStephenson/STL-Inventory/pull/446)) — index an arbitrary folder as inbox models (`is_inbox` flag) without adding it as a permanent scan root; each immediate subdir is treated as a creator. Inbox models anchor in the managed library on reorganize apply (clearing `is_inbox`), and restore on undo |
| [#429](https://github.com/RBStephenson/STL-Inventory/issues/429) | **Bulk-enrich metadata** ([#436](https://github.com/RBStephenson/STL-Inventory/pull/436)) — `PATCH /models/bulk/enrich` sets creator/character/title across a multi-selection; the Enrich mode in the bulk toolbar — the bridge to reorganize-eligibility |
| [#450](https://github.com/RBStephenson/STL-Inventory/issues/450) | **Named libraries + source→library mapping** ([#454](https://github.com/RBStephenson/STL-Inventory/pull/454)) — a library is a named, writable scan root; a source folder maps to a destination library, inherited by its packs |
| [#451](https://github.com/RBStephenson/STL-Inventory/issues/451) | **Pack-grouped preview projection** ([#455](https://github.com/RBStephenson/STL-Inventory/pull/455)) — `GET /import/preview` groups inbox models into one card per pack with inherited destination |
| [#453](https://github.com/RBStephenson/STL-Inventory/issues/453) | **Stage + batch apply** ([#460](https://github.com/RBStephenson/STL-Inventory/pull/460)) — `POST /import/apply` moves imported packs into their mapped library via the reorganize engine (drift + undo, `is_inbox` cleared) |

**Post-release hardening** (v0.12.1 – v0.12.3) — bulk-enrich and painting-guide
fixes shipped after the feature line:
[#437](https://github.com/RBStephenson/STL-Inventory/issues/437) /
[#438](https://github.com/RBStephenson/STL-Inventory/issues/438) /
[#439](https://github.com/RBStephenson/STL-Inventory/issues/439) (bulk-enrich
rescan overwrite, clearing character/title, whitespace-only creator),
[#440](https://github.com/RBStephenson/STL-Inventory/issues/440) (sanitize
imported guide HTML/CSS/URLs),
[#441](https://github.com/RBStephenson/STL-Inventory/issues/441) /
[#442](https://github.com/RBStephenson/STL-Inventory/issues/442) /
[#445](https://github.com/RBStephenson/STL-Inventory/issues/445) (PaintRack CSV
removal/duplicate-identity guards),
[#443](https://github.com/RBStephenson/STL-Inventory/issues/443) /
[#444](https://github.com/RBStephenson/STL-Inventory/issues/444) (brand-aware
guide-import overrides + no silent drop of undecided paints).

---

## v0.13 — Import Preview screen & painting mix swatches ✅ Complete

Released as **v0.13.0**. Completed the browse-first **Import Preview** screen on
top of the v0.12 foundation, and added true paint-mix modelling.

| Issue | Item |
|-------|------|
| [#449](https://github.com/RBStephenson/STL-Inventory/issues/449) | **Epic — Import Preview screen** — browse-first folder → library with inline enrich |
| [#452](https://github.com/RBStephenson/STL-Inventory/issues/452) | **Import Preview UI** ([#457](https://github.com/RBStephenson/STL-Inventory/pull/457), [#459](https://github.com/RBStephenson/STL-Inventory/pull/459)) — pack cards, inline metadata editor, destination dropdown, per-card import; library name/writable toggle in Settings |
| [#456](https://github.com/RBStephenson/STL-Inventory/issues/456) | **Per-pack file counts** in the preview cards |
| [#458](https://github.com/RBStephenson/STL-Inventory/issues/458) | **Pack-card C3** — Notes, Source URL + Fetch, and Collections on pack cards |
| [#425](https://github.com/RBStephenson/STL-Inventory/issues/425) | **True mix swatches (Option B)** — nullable `paint_id`, mix components with ratios, round-trip, blended-dot chip |
| [#271](https://github.com/RBStephenson/STL-Inventory/issues/271) | **Painting round-trip coverage** — sub-content callouts and wargaming raw-block capture closed the importer gaps surfaced across the corpus |

---

## v0.14 — Desktop shell & painting/variant polish ✅ Complete

Released as **v0.14.0**.

| Issue | Item |
|-------|------|
| [#463](https://github.com/RBStephenson/STL-Inventory/issues/463) | **Desktop app shell** — the standalone build opens in a native window via **pywebview** (WebView2 on Windows), with an automatic fall-back to the default browser; `STL_NO_WINDOW=1` forces browser mode |
| [#500](https://github.com/RBStephenson/STL-Inventory/issues/500) | **Variant group: bulk-set store page** ([#501](https://github.com/RBStephenson/STL-Inventory/pull/501)) — set one store/product URL across the selected variants of a group in a single step (selection-scoped, overwriting) |
| [#425](https://github.com/RBStephenson/STL-Inventory/issues/425) → [#477](https://github.com/RBStephenson/STL-Inventory/issues/477) | **Nullable `paint_id` for unresolved single swatches** — an unresolved single-paint swatch is kept by name rather than dropped, like mix components |
| [#415](https://github.com/RBStephenson/STL-Inventory/issues/415) | **Back-reference mix components** — closed as covered by #425 (unresolved components round-trip as named rows; no real corpus cases warranted a structural ref) |

---

## v0.15 — In-app guide authoring ✅ Complete

Released as **v0.15.0**. Extended the structured guide editor (shipped in v0.8)
into a complete from-scratch authoring path, so a guide can be built and
published entirely in the app without hand-writing HTML.

| Issue | Item |
|-------|------|
| [#484](https://github.com/RBStephenson/STL-Inventory/issues/484) | **Epic — in-app authoring & validation** |
| [#487](https://github.com/RBStephenson/STL-Inventory/issues/487) | Guide-start wizard |
| [#488](https://github.com/RBStephenson/STL-Inventory/issues/488) | Structured editor — inventory-backed swatch picker, value%/reorder + live preview |
| [#503](https://github.com/RBStephenson/STL-Inventory/issues/503) | Drag-reorder tabs/phases/steps/swatches in the editor |
| [#489](https://github.com/RBStephenson/STL-Inventory/issues/489) | Validation panel — wire the validator; block publish on errors |
| [#490](https://github.com/RBStephenson/STL-Inventory/issues/490) | Series-bundle PDF + reward stamping |
| [#511](https://github.com/RBStephenson/STL-Inventory/issues/511) | Guide export UI — series-bundle download + stamping controls |

---

## v0.15.1 — Guide theming & Paint Shelf independence ✅ Complete

Make guides customizable to each user's style before the AI work lands, and
decouple the Paint Shelf from the guides feature so it's always available.

| Issue | Item |
|-------|------|
| [#513](https://github.com/RBStephenson/STL-Inventory/issues/513) | **Epic — guide theming & Paint Shelf independence** |
| [#514](https://github.com/RBStephenson/STL-Inventory/issues/514) | App-level default guide theme + new-guide inheritance |
| [#515](https://github.com/RBStephenson/STL-Inventory/issues/515) | Guide theme editor UI (colour pickers + live preview) + PDF theme rendering |
| [#516](https://github.com/RBStephenson/STL-Inventory/issues/516) | Paint Shelf made independent of the guides feature flag (always visible) |

---

## v0.16 — AI drafts & color match ✅ Complete

The painting module's headline workflow: an LLM produces a first-draft guide as
structured data, you edit it, and a colour-match studio suggests owned paints
from a reference image. Domain rules are captured in
[`docs/painting/reference/figure-painting-skill.md`](docs/painting/reference/figure-painting-skill.md).
This release also **renames the app to STL Studio** (the catalog keeps the name
*Library*) to reflect its growth into a 3D-print + painting toolbox.

| Issue | Item |
|-------|------|
| [#485](https://github.com/RBStephenson/STL-Inventory/issues/485) | **Epic — AI draft & color match** |
| [#491](https://github.com/RBStephenson/STL-Inventory/issues/491) | Generation service — Claude → GuideDraft, async `/draft` (`generation.py`) |
| [#492](https://github.com/RBStephenson/STL-Inventory/issues/492) | Draft → edit review flow |
| [#493](https://github.com/RBStephenson/STL-Inventory/issues/493) / [#561](https://github.com/RBStephenson/STL-Inventory/issues/561) | Color-match studio — Lab / CIEDE2000 / k-means, eyedropper, background exclusion |
| [#569](https://github.com/RBStephenson/STL-Inventory/issues/569) | Color match — hue-cohesive value ladder (shadow / mid / highlight) |
| [#494](https://github.com/RBStephenson/STL-Inventory/issues/494) | Reference-image pipeline — STL-folder rung + provenance (`images.py`) |
| [#535](https://github.com/RBStephenson/STL-Inventory/issues/535) / [#536](https://github.com/RBStephenson/STL-Inventory/issues/536) | Reference image — upload + Claude vision, in-browser downscale |
| [#498](https://github.com/RBStephenson/STL-Inventory/issues/498) / [#506](https://github.com/RBStephenson/STL-Inventory/issues/506) | Validation — domain colour rules: skin-anchor band + highlight-direction |
| [#517](https://github.com/RBStephenson/STL-Inventory/issues/517) | AI/Painting settings — capture + encrypt the API key (shown only when guides are enabled) |
| [#504](https://github.com/RBStephenson/STL-Inventory/issues/504) | Guide editor — author/edit mix-component swatches (ratios) |

All AI capabilities are bring-your-own-API-key; no keys ship in the repo or build.

> Deferred to v0.17.0: the reference-image network rungs (assisted web search /
> AI-gen) — [#563](https://github.com/RBStephenson/STL-Inventory/issues/563).

---

## v0.17.0 — Painting full-corpus & wargaming 🗓 Planned

| Issue | Item |
|-------|------|
| [#486](https://github.com/RBStephenson/STL-Inventory/issues/486) | **Painting M5 — full-corpus import & polish** — bulk-import the reference guide corpus as reviewed drafts, calibrate the validator, print/PDF + accessibility pass |
| [#409](https://github.com/RBStephenson/STL-Inventory/issues/409) | **Structured wargaming guide type** — `guide_type` discriminator + quality tiers / batch workflow / basing |
| [#563](https://github.com/RBStephenson/STL-Inventory/issues/563) | Reference-image network rungs — assisted web search / AI-gen + hero credit |

---

## v1.0 — Desktop shell (final polish) 🚧 In progress

The 1.0 release is the desktop-experience polish pass.

| Issue | Item |
|-------|------|
| [#528](https://github.com/RBStephenson/STL-Inventory/issues/528) | ✅ **Desktop shell: pywebview → Electron** — Windows ships a real NSIS-installed Electron app (Start-menu entry, app icon, no console window); the Python backend runs as a windowless sidecar on a dynamic port. Unsigned, auto-update deferred |

Follow-ups deferred out of the v1 Electron scope: **code signing** (ships unsigned;
SmartScreen warns on first run), **auto-update** (electron-updater feed), and
**Linux/macOS Electron packaging** — Linux keeps the loose binary + browser
fallback for now. macOS notarization ([#17](https://github.com/RBStephenson/STL-Inventory/issues/17))
sits in the backlog — deferred until there's appetite for the Apple Developer
Program cost.

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
- **Authoring polish** (milestone **v0.15**, epic [#484](https://github.com/RBStephenson/STL-Inventory/issues/484)) —
  a from-scratch guide wizard, a validation panel, and series-bundle PDF, building
  on the M3 editor.
- **M4 — AI drafts + color match** (milestone **v0.16**, epic [#485](https://github.com/RBStephenson/STL-Inventory/issues/485)) —
  the Claude generation service (`generation.py`), draft→edit flow, the color-match
  studio (`colormatch.py`), and the reference-image pipeline (`images.py`); all
  three services are stubs today. Domain rules are captured in
  [`docs/painting/reference/figure-painting-skill.md`](docs/painting/reference/figure-painting-skill.md).
- **M5 — Full-corpus import & polish** (milestone **v1.0**, epic [#486](https://github.com/RBStephenson/STL-Inventory/issues/486)) —
  bulk-import the reference guide corpus as reviewed drafts, calibrate the
  validator, and do the print/PDF + accessibility pass.

The shared skills tabs are reference content rendered from a built-in port;
fleshing out the sparse **Brush Skills** tab is tracked in
[#483](https://github.com/RBStephenson/STL-Inventory/issues/483) (backlog).

---

## Stretch goals / backlog

Larger, well-defined efforts not tied to a near-term milestone.

| Issue | Item |
|-------|------|
| [#16](https://github.com/RBStephenson/STL-Inventory/issues/16) | **Cross-model kit building (kitbash)** — assemble a character from parts across multiple packs; needs cross-model part-picker UI design |
| [#17](https://github.com/RBStephenson/STL-Inventory/issues/17) | **Notarize the macOS standalone binary** — deferred; requires a paid Apple Developer Program membership |

---

Have an idea or want to pick something up? Check the
[open issues](https://github.com/RBStephenson/STL-Inventory/issues) or open a new one.
