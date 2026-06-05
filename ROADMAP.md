# Roadmap

This roadmap is organized by planned release milestone. Items within a milestone are roughly ordered by priority, but exact sequencing shifts as work progresses. Issues tagged [`good first issue`](https://github.com/RBStephenson/STL-Inventory/issues?q=is%3Aopen+label%3A%22good+first+issue%22) are a good starting point for new contributors.

---

## v0.5 — Library polish & scan reliability

Core UX gaps and scan accuracy improvements.

| Issue | Item |
|-------|------|
| ~~[#101](https://github.com/RBStephenson/STL-Inventory/issues/101)~~ | ~~**Prev/Next navigation on model detail** — move through the library one model at a time without returning to the grid~~ |
| [#100](https://github.com/RBStephenson/STL-Inventory/issues/100) | **Capture thumbnail from the 3D viewer** — solves no-thumbnail for STL-only models by snapping the current view |
| ~~[#106](https://github.com/RBStephenson/STL-Inventory/issues/106)~~ | ~~**Manual force-group override** — let users fix mis-grouped variants the heuristic can't resolve automatically~~ |
| [#107](https://github.com/RBStephenson/STL-Inventory/issues/107) | **Strip creator tags from variant grouping keys** — cleans up studio-tag stragglers; bundle with #106 |
| [#53](https://github.com/RBStephenson/STL-Inventory/issues/53) | **Prune stale models after full scan** — removes DB rows for folders the current walk no longer visits |
| [#50](https://github.com/RBStephenson/STL-Inventory/issues/50) | **Per-creator rescan bootstrap** — currently silently does nothing when a creator has zero indexed models |

---

## v0.6 — Configuration & storefront expansion

Preference persistence (#32) is a prerequisite for several items here.

| Issue | Item |
|-------|------|
| [#32](https://github.com/RBStephenson/STL-Inventory/issues/32) | **Server-side persisted preferences** — NSFW default, page size, sort, filter presets (currently lost between browsers) |
| [#31](https://github.com/RBStephenson/STL-Inventory/issues/31) | **Configurable scan rules** — ignore patterns, custom parts-folder names, toggle auto-tag inference |
| [#51](https://github.com/RBStephenson/STL-Inventory/issues/51) | **Optional Lychee / Chitubox slicer file support** — opt-in setting to index pre-sliced files alongside STLs |
| [#102](https://github.com/RBStephenson/STL-Inventory/issues/102) | **Loot Studios storefront enrichment** — subscriber-gated; requires session/cookie auth flow and a Settings UI |
| [#33](https://github.com/RBStephenson/STL-Inventory/issues/33) | **Document Docker drive-mount configuration** — a recurring stumbling block for new Docker users |

---

## v0.7 — Distribution & infrastructure

| Issue | Item |
|-------|------|
| [#17](https://github.com/RBStephenson/STL-Inventory/issues/17) | **Notarize macOS binary** — removes the right-click → Open Gatekeeper workaround; requires an Apple Developer account |
| [#43](https://github.com/RBStephenson/STL-Inventory/issues/43) | **Adopt Alembic for DB migrations** — the hand-rolled `ALTER TABLE` startup loop only supports additive changes |
| [#24](https://github.com/RBStephenson/STL-Inventory/issues/24) | **Code-split the frontend bundle** — lazy-load the 3D viewer to bring the 1.17 MB bundle under control |

---

## Stretch goals

Large features that are well-defined but each represent a significant project.

| Issue | Item |
|-------|------|
| [#16](https://github.com/RBStephenson/STL-Inventory/issues/16) | **Cross-model kit building (kitbash)** — assemble a character from parts across multiple packs |
| [#29](https://github.com/RBStephenson/STL-Inventory/issues/29) | **Reorganize library on disk** — preview → apply with manifest/undo; standalone-only (Docker mounts are read-only) |

---

## Good first issues

| Issue | Item |
|-------|------|
| [#19](https://github.com/RBStephenson/STL-Inventory/issues/19) | Replace deprecated `datetime.utcnow()` with timezone-aware UTC |
| [#18](https://github.com/RBStephenson/STL-Inventory/issues/18) | Migrate startup hooks to FastAPI lifespan |

---

Have an idea or want to pick something up? Check the [open issues](https://github.com/RBStephenson/STL-Inventory/issues) or open a new one.
