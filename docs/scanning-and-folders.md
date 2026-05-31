# Scanning & Folder Structure

This explains how STL Inventory reads your library — useful if your models are
laid out unusually or aren't being detected the way you'd expect.

- [The folder layout it expects](#the-folder-layout-it-expects)
- [How a "model" is detected](#how-a-model-is-detected)
- [Thumbnails](#thumbnails)
- [Automatic tagging](#automatic-tagging)
- [needs_review](#needs_review)
- [Full scan vs. per-creator rescan](#full-scan-vs-per-creator-rescan)
- [Incremental scanning](#incremental-scanning)
- [Orynt3D support](#orynt3d-support)

---

## The folder layout it expects

The scanner is built around this general shape, but it's flexible about depth:

```
<scan root>/
  <Creator>/                         ← top-level folder = a creator
    config.orynt3d                   ← optional creator metadata
    <Character or Product>/          ← a grouping folder (optional)
      Images/  Renders/  …           ← preview images (any common name)
      <Variant>/                     ← e.g. "Bust", "1:6 Pre-supported"  ← a MODEL
        head.stl  body.stl  base.stl
      <Another Variant>/             ← a separate MODEL
```

Key ideas:

- **The top-level folder under a scan root is always a creator** — never a model
  itself, even if its name contains a word like "Figures" or "Miniatures."
- A **model** is a folder containing the actual printable parts for one product
  or variant.
- Folders below a model (e.g. `head/`, `base/`, `Supported/STL/`) are treated as
  **parts of that model**, not separate models.

## How a "model" is detected

For each folder, the scanner decides "is this a model?" in priority order:

1. **Orynt3D config** — if the folder has a `config.orynt3d` marking it as a
   model, that's authoritative.
2. **Name signals** — the folder name contains scale/type/modifier hints
   (e.g. `1:6`, `Bust`, `Pre-supported`), marking a product boundary.
3. **Parts pattern** — the folder has STLs and its sub-folders look like parts
   (`head`, `base`, `supported`…).
4. **Deepest fallback** — the folder has STLs and nothing below it has STLs.

If none match, the scanner recurses deeper, carrying the folder name along as
**character** context (which powers [variant grouping](features.md#variant-grouping)).

## Thumbnails

For each model the scanner looks for a preview image, walking **upward** from the
model folder toward the creator folder. It prefers images in folders named like
`Renders`, `Images`, `Photos`, `Preview`, `Gallery`, etc., then any loose image,
then any image in a non-model sub-folder. This is why a shared `Renders/` folder
at the character level still gives each variant a thumbnail.

If the thumbnail it picks is wrong, override it with the
[image picker](features.md#image-picker-thumbnails).

## Automatic tagging

From folder and file names, the scanner auto-detects and tags:

- **Scale** — ratio scales like `1:6`, `1:9`, `1:12` (including glued forms like
  `1_12scale`), and miniature heights like `28mm`, `75mm`.
- **Type** — `bust`, `statue`, `figure`, `diorama`, `chibi`, `miniature`,
  `terrain`, and more.
- **Modifiers** — `pre-supported`, `uncut`, `NSFW`, `pin-up`, etc.

Collector-scale ratios (1:4 through 1:12) also auto-add the **`statue`** tag,
since figures at those scales are statues by convention.

These appear as **auto-tags** on the model and feed the Library's tag filter.
Auto-tags are kept separate from tags you add yourself, and a rescan refreshes
them — so as detection improves, your tags improve too.

## needs_review

When the scanner finds a folder it isn't confident about — no Orynt3D config, no
name signals, and no STL files directly inside it — it flags the model
`needs_review` so you can confirm or fix it in the
[Triage queue](features.md#triage-queue). Models that clearly have STL files or
Orynt3D metadata are never flagged, and the flag is cleared automatically once a
model is confirmed.

## Full scan vs. per-creator rescan

- **Full scan** (Scan Library button) walks every scan root and every creator.
  Use it for the first scan, or after adding lots of new creators.
- **Per-creator rescan** (Rescan button on the
  [Creators page](features.md#creators--per-creator-rescan)) re-walks just one
  creator's folder. Since you usually add models one creator at a time, this is
  the fast way to pick up new additions without re-scanning your whole library.

Only one scan runs at a time — starting one while another is running is blocked.

## Incremental scanning

A full scan is **incremental**: folders whose modification time hasn't changed
since the last scan skip the expensive file-indexing step. Metadata and tags are
still refreshed every scan, so improvements to tag detection (like new scale
rules) are picked up even on unchanged folders.

A **per-creator rescan** always does a full reindex of that creator, so it's the
reliable way to force everything for one creator to be re-read.

## Orynt3D support

If you organize your library with **Orynt3D**, the scanner reads its
`config.orynt3d` files. Creator-level configs supply the creator name and source
info; model-level configs supply titles, notes, tags, collections, source links,
and cover images. Orynt3D-provided metadata takes precedence over guessed values.
