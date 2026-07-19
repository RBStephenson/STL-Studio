# Scanning & Folder Structure

This explains how STL Studio reads your library — useful if your models are
laid out unusually or aren't being detected the way you'd expect.

- [The folder layout it expects](#the-folder-layout-it-expects)
- [Custom folder layouts](#custom-folder-layouts)
- [How a "model" is detected](#how-a-model-is-detected)
- [STL file part names](#stl-file-part-names)
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
  Slicer project and slice files (`.lys`, `.chitubox`, `.ctb`, `.photon`,
  `.pw0`/`.pwx`/`.pws`, `.fhd`) are never indexed, and any indexed by older
  versions are cleaned up after the next full scan.
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

Structural folders — support status (`Supported`/`Unsupported`/`Presupported`),
containers/formats (`STL`, `Lychee`, and slicer folders like `LYS`, `CTB`,
`Chitu`), pre-slice prep (`Sliced`/`Presliced`), render folders (`Renders`,
`Images`), and pure scale/cut descriptors — are **never** used as the character.
Otherwise every creator's `LYS` (or `STL`, `Supported`, …) folder would collapse
into one giant cross-character variant group. The real character is inherited from
the nearest meaningful ancestor instead, so `Spiderman/Supported/LYS/` groups under
*Spiderman*. A model left with a stale structural name by an older scan (e.g. a
folder that used to be called `LYS`) self-heals to the derived character name on
the next rescan — a genuine name you set yourself is always left untouched.

When the heuristic gets it wrong, you can fix it by
[merging the model into a group](features.md#fixing-mis-grouped-models) —
the correction is a durable group membership, so future rescans leave it
alone instead of re-deriving it from the heuristic.

### Models versus release packages

A scanned **model** is a catalog/viewer unit; a **release package** is a physical
move boundary. One package may contain several models, such as printable files at
its root plus a separately indexed `Alternate/` subtree. With **Preserve release
package structure** enabled under **Settings → Library**, Reorganize finds the
physical character ancestor and treats its next child as the package root. It then
moves that complete subtree while keeping all relative folders and companion files
unchanged. A model stored directly in the character directory uses that directory
as its package boundary. If the stored character cannot be matched to an ancestor
folder, Reorganize blocks the package for review rather than flattening it. See
[Reorganize Library](features.md#reorganize-library).

Folders and files beside those package roots form the **character envelope**. This
commonly includes shared `img/`, `Images/`, or `Renders/` folders, but unrecognized
loose companion files are protected the same way. Reorganize moves the envelope
only when every package under the character is selected. With a partial selection
it remains at the original character path, and the preview explicitly reports that
it will be retained.

## STL file part names

Each STL file's **Name** (`part_name`, shown in the model detail file list) is
auto-derived from its filename the first time the scanner indexes it —
underscores/hyphens become spaces, each word is title-cased, and a
`Sup_`-prefixed or `-supported`-suffixed file gets a leading "Supported ". This
happens for both a regular library scan and an [imported](features.md#import-folder)
folder — both go through the same indexer. It's a one-time default: once set,
a rescan never overwrites it, so a manual rename or an
[AI Organize](features.md#model-detail) suggestion always sticks.

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

## Scan rules

The built-in detection above can be extended under **Settings → Scan Rules**.
Every rule list *adds* to the defaults (it never replaces them) and applies on the
next scan. See [Scan rules](features.md#scan-rules) for the full description:

- **Ignore patterns** — skip folders by name (`WIP`) or path glob (`*/_archive/*`).
- **Tag rules** — add an auto-tag when a name contains a keyword (`Aztec` → `civ`).
- **Parts folder names** — extra exact folder names treated as parts/structure.

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

A full scan also cleans up file records left behind by a rename done outside
the app (e.g. a bulk lowercase/hyphenate pass run directly on disk): any STL
file record whose path no longer resolves, in a model folder that's otherwise
still present, is removed. Without this, [Reorganize](features.md#reorganize-library)
would keep reporting that model as having "missing files" indefinitely — the
old record never goes away on its own, since indexing only ever adds newly
found files, it doesn't remove ones whose path changed. A per-creator rescan
doesn't need this: it already fully reindexes that creator's files from
scratch every time.

## Incremental scanning

A full scan is **incremental**: folders whose modification time hasn't changed
since the last scan skip the expensive file-indexing step. Metadata and tags are
still refreshed every scan, so improvements to tag detection (like new scale
rules) are picked up even on unchanged folders.

A **per-creator rescan** always does a full reindex of that creator, so it's the
reliable way to force everything for one creator to be re-read.

## Libraries (import destinations)

A **library** is a scan root you've given a name and marked as a writable
**import destination**. It's the folder the [Import](features.md#import-folder)
flow files packs into.

Configure one in **Settings**, on a folder's card:

- **Library** — a display name (e.g. `minis`). Shown in the import screen's
  destination dropdown; defaults to the folder's basename if left blank.
- **Import destination** — tick this to mark the folder writable as a move
  target. Only ticked folders appear in the import dropdown. Untouched folders
  remain index-only (scanned in place, never moved into).

If the destination drive isn't a scan root yet, add it first under **Settings →
Add a Folder**, then name it and tick **Import destination**.

Marking a folder an import destination only makes it *eligible*. The actual
on-disk move still requires the **Reorganize Library** feature flag
(`reorganize_enabled`) to be turned on under **Settings → Library** — it defaults
off, and while off both Reorganize and import moves are refused. This mirrors
[Reorganize](features.md#reorganize-library)'s safety posture.
