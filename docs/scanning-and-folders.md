# Scanning & Folder Structure

This explains how STL Inventory reads your library — useful if your models are
laid out unusually or aren't being detected the way you'd expect.

- [The folder layout it expects](#the-folder-layout-it-expects)
- [Custom folder layouts](#custom-folder-layouts)
- [How a "model" is detected](#how-a-model-is-detected)
- [Thumbnails](#thumbnails)
- [Automatic tagging](#automatic-tagging)
- [needs_review](#needs_review)
- [Full scan vs. per-creator rescan](#full-scan-vs-per-creator-rescan)
- [Incremental scanning](#incremental-scanning)

---

## The folder layout it expects

The scanner is built around this general shape, but it's flexible about depth:

```
<scan root>/
  <Creator>/                         ← top-level folder = a creator
    <Character or Product>/          ← a grouping folder (optional)
      Images/  Renders/  …           ← preview images (any common name)
      <Variant>/                     ← e.g. "Bust", "1:6 Pre-supported"  ← a MODEL
        head.stl  body.stl  base.stl
      <Another Variant>/             ← a separate MODEL
```

Key ideas:

- **By default, the top-level folder under a scan root is a creator** — never a
  model itself, even if its name contains a word like "Figures" or "Miniatures."
  If your creators live deeper (e.g. under a genre folder), set a
  [custom layout](#custom-folder-layouts) per scan root.
- A **model** is a folder containing the actual printable parts for one product
  or variant. A folder is only ever indexed as a model if its subtree contains
  3D files (`.stl` / `.3mf` / `.obj`) — render/preview-only folders are skipped.
- Folders below a model (e.g. `head/`, `base/`, `Supported/STL/`) are treated as
  **parts of that model**, not separate models.

## Custom folder layouts

If your library doesn't put creators at the top level, you can tell each scan
root how its folders are arranged with a **layout template** (Settings → the
*Layout* field on each scan location). A template describes the levels **above
your models**, one per `/`, down to the level that names the creator:

| Token | Meaning |
|---|---|
| `{creator}` | This level's folder name is the **creator**. Required, and must be the **last** token. |
| `{tag}` | This level's folder name is added as an **auto-tag** to every model beneath it (e.g. a genre or collection folder). |
| `{ignore}` (or `*`) | A structural level that's walked past and carries no meaning. |

Everything **below** the creator level is still detected automatically (the
character/variant/model heuristics below), so you only describe the part of the
tree above your products.

Examples:

| Template | Disk layout | Result |
|---|---|---|
| `{creator}` *(default)* | `Abe3D/…` | Top folders are creators — today's behavior. |
| `{tag}/{creator}` | `Sci-Fi/Abe3D/…` | Creators sit under a genre folder; every model gets a `sci-fi` tag. |
| `{tag}/{tag}/{creator}` | `Sci-Fi/Mechs/Abe3D/…` | Two tag levels — models tagged `sci-fi` and `mechs`. |
| `{ignore}/{creator}` | `_incoming/Abe3D/…` | A wrapper folder is skipped; creators sit one level down. |

The same creator can appear under more than one `{tag}` branch — its models are
merged under one creator, each keeping the tag from its own path. Changing a
layout takes effect on the next scan (full or per-creator).

## How a "model" is detected

For each folder (that contains 3D files somewhere in its subtree), the scanner
decides "is this a model?" in priority order:

1. **Name signals** — the folder name contains scale/type/modifier hints
   (e.g. `1:6`, `Bust`, `Pre-supported`), marking a product boundary.
2. **Parts pattern** — the folder has STLs and its sub-folders look like parts
   (`head`, `base`, `supported`…).
3. **Deepest fallback** — the folder has STLs and nothing below it has STLs.

If none match, the scanner recurses deeper, carrying the deepest **meaningful**
(non-structural) folder name along as **character** context, which powers
[variant grouping](features.md#variant-grouping).

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

When the scanner finds a folder it isn't confident about — no name signals and no
STL files directly inside it (only found recursively) — it flags the model
`needs_review` so you can confirm or fix it in the
[Triage queue](features.md#triage-queue). Models that clearly have STL files are
never flagged, and the flag is cleared automatically once a model is confirmed.

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
