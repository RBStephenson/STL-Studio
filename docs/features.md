# Feature Guide

A tour of every screen and what it does.

- [Library](#library)
- [Variant grouping](#variant-grouping)
  - [Fixing mis-grouped models](#fixing-mis-grouped-models)
- [Model detail](#model-detail)
- [3D viewer](#3d-viewer)
- [Image picker (thumbnails)](#image-picker-thumbnails)
- [Favorites, print queue & printed tracking](#favorites-print-queue--printed-tracking)
- [Kit Builder](#kit-builder)
- [Metadata editing & web enrichment](#metadata-editing--web-enrichment)
- [Triage queue](#triage-queue)
- [Collections](#collections)
- [Bulk editor (tags & enrich)](#bulk-editor-tags--enrich)
- [Import folder](#import-folder)
- [Creators & per-creator rescan](#creators--per-creator-rescan)
- [Reorganize library](#reorganize-library)
- [Settings](#settings)
- [AI & Integrations](#ai--integrations)
- [Logging](#logging)
- [Backup, restore & reset](#backup-restore--reset)
- [NSFW toggle](#nsfw-toggle)

---

## Library

The main grid. Every filter lives in the URL, so you can bookmark or share a
filtered view.

- **Search** by name, title, description, or character.
- **Filters:** creator (include or exclude), source site, tag, NSFW, has-image,
  needs-review, min star rating, favorites, in-queue, and printed. Open the
  **Filters** panel for the full set, or use the quick chips in the header
  (e.g. "*N* favorites", "*N* queued", "*N* printed") — so you can see both
  what you want to print and what you've already printed.
- **Negative tag filter:** clicking a tag cycles through three states —
  **include** (show only models with the tag), **exclude** (a `≠ tag` chip;
  hides models with the tag), and **off**. Only one include and one exclude tag
  apply at a time.
- **Hide printed:** the **hide printed** chip excludes models you've already
  printed (status *printed*), leaving queued and not-yet-printed models. It's
  the inverse of the *printed* chip, and the two are mutually exclusive.
- **Sort:** the **Sort** dropdown in the header orders the grid by **Name**,
  **Date added** (newest first), or **Creator**. The choice is captured in saved
  presets and remembered as your default across browsers; Prev/Next on a model's
  detail page walks the library in the same order. (The Recently added chip
  forces newest-first while it's on.)
- **Recently added:** a quick chip in the header filters to models added in the
  last *N* days, newest first, and cards inside that window carry a **New**
  badge. The window (3 / 7 / 14 / 30 days) is configurable under
  **Settings → Preferences**.
- **Saved presets:** once you've dialed in a set of filters, save it as a named
  preset and re-apply it with one click. Presets are stored server-side, so they
  follow you across browsers and devices.
- **Pagination:** Prev / page number / Next, with a jump-to-page box — shown at
  both the top and bottom of the grid so you can page without scrolling. The
  page size (25 / 50 / 100) is configurable under **Settings → Preferences**,
  along with the other server-side preferences (NSFW default, filter presets).

Each card shows the thumbnail, name, tags, and small action icons (favorite ★
and print-queue 🖨) that appear on hover. You can also **drag a card by its
hover grip onto another card to group them as variants** — see
[Variant grouping](#variant-grouping).

**Keyboard shortcuts:** the grid is fully keyboard-drivable. Press `/` to jump to
the search box, `A`/`D` and `W`/`S` (or the arrow keys) to move the focus ring
between cards, `Enter` to open the focused model, and `Esc` to blur search or
clear the focus ring. You can also **group cards from the keyboard**: `Tab` to a
card's grip handle, `Space` to pick it up, the arrow keys to move it onto a
target card, then `Space`/`Enter` to group them (`Esc` cancels). Press `?` (or
the keyboard button in the header) at any time to see the full list.

## Variant grouping

When several folders share the same character (for example a *Bust*, a
*Full size*, and a *Pre-supported* version of the same figure), the Library
collapses them into a **single group card** with a "*N* variants" badge.
Click it to open the group and see each variant individually.

This keeps the grid tidy when a creator ships many cuts/versions of one model.

### Group variants by character folder (opt-in)

If your library is laid out as `{creator}/{character}/…` — every variant of a
figure living somewhere under one character folder — you can skip the name
heuristic entirely. Turn on **Group variants by character** for a scan root
(Settings → Library, next to its layout) and the scanner treats the first folder
below the creator as the group: *everything* beneath it becomes one variant
group, regardless of how the sub-folders are named. Off by default; **rescan to
apply**. Manual group overrides still win.

### Fixing mis-grouped models

The scanner infers the character group from folder names — it's accurate for
most layouts but occasionally gets it wrong (typo'd folder, unusual nesting,
inconsistent studio naming). You can fix any mis-grouping durably, so your
correction survives future rescans:

**Drag-to-group from the Library** (fastest for grouping loose models)

In the main Library view, hover a model card and a small **grip handle**
appears in its bottom-left corner. Drag the card onto another card from the
**same creator** to group them:

- **Onto an existing group** — the dragged model is added to that group straight
  away, taking on its name.
- **Onto a loose card** — a naming prompt opens (pre-filled with the target's
  display name); confirm or edit the name and both models join that group.
- **Multi-select drag** — select several cards with their checkboxes first, then
  drag any one of them to group the whole selection in a single step. The drag
  preview shows a count badge.
- **Merge two groups** — drag a **group** card onto another card. A confirmation
  asks before moving every member of the dragged group into the target group
  (the dragged group's name is discarded).

Grouping only works within a single creator (cards from other creators in a
multi-selection are skipped), and only in the default Library view (it's off in
the favorites/queue/printed/excluded views, which show flat cards).

The whole gesture is keyboard-accessible: `Tab` to a card's grip, `Space` to
pick it up, arrow keys to move it onto the target, `Space`/`Enter` to drop and
group (`Esc` cancels). Screen readers announce the pickup, the card you're over,
and the result.

**From the group view** (fastest for fixing a whole group at once)

Open a group card to see all its variants. The group view manages the whole
group as well as individual variants:

- **Rename the group** — click the group title in the header to edit it in
  place. Saving renames *every* variant in the group and takes you to the
  renamed group.
- **Bulk actions** — tick the checkbox on each card you want (or **Select
  all**), then use the toolbar that appears:
  - **Move to group** — type a target group name (with existing-group
    suggestions); the selected models move there. Moving into a group that
    already exists is how you **merge** groups.
  - **Set image** — paste an image URL (or a product-page link, whose preview
    image is used) to give *every* selected variant the same thumbnail. The
    image is downloaded once and applied to all of them.
  - **Set store page** — paste a store/product URL to write it as the
    **source link** on the selected variants. Variants of one figure usually
    share a single store listing, so this fills the store page across them in
    one step. It applies to exactly the variants you've ticked (overwriting any
    existing link on those) and leaves unticked siblings alone — so you can set
    one listing on most variants while keeping a different link on the odd one
    out.
  - **Ungroup** — pull the selected models out of the group, making them
    standalone models in the Library.
- **Per-card actions** — below each card, **Move to group** (with name
  suggestions), the **image button** (**Set as group thumbnail**), and
  **× Remove** act on that one variant.
- **Pick the group thumbnail** — the group's Library card borrows one
  variant's image. By default the representative variant is chosen
  automatically: a variant you've **favorited or queued** is promoted to the
  front so its ★/🖨 chip shows on the group card, otherwise a variant that
  *has* a thumbnail represents the group. Click the **image button** under any
  variant to override and make it the group's display image instead — that
  choice is saved and survives rescans.
- **Reorder within a group** — drag variant cards within the group view to set
  a custom display order. The order persists until you reset it.

Models that move or ungroup leave the current list immediately. When the last
variant leaves, the group view closes back to where you came from.

**From a model's detail page**

Click a model, then find the **Merge into group** button in the header
(alongside *Edit*, *Find on Web*, and *Split pack*):

- Click **Merge into group** to open an inline input. Start typing — existing
  groups for that creator appear as suggestions so you can pick from a list
  rather than type the full name from memory. Confirm an existing group's
  name to join it. (This only joins an *existing* group — to build a brand-new
  group from a single loose model, use drag-to-group or the group view
  instead.)
- Once grouped, the button changes to an indigo **Group: [name]** chip. Click
  it to merge into a different group, or click **✕** beside it to remove the
  model from the group.

**How grouping durability works**

Every manual grouping action — drag-to-group, merge, split, rename, "Merge
into group" — writes directly to a durable **variant group** record, applied
immediately (no rescan needed). Because the group is a first-class record
rather than a per-model note, a future rescan never undoes it: the scanner's
auto-grouping only ever proposes groups for models that aren't already in one.

Removing a model from a group (via **Ungroup**, **× Remove**, or clearing
**Set group**) pins it as explicitly ungrouped, sticky across rescans, so the
scanner won't just re-propose the same group next time. Explicitly regrouping
it (drag, merge, or **Set group** again) clears that pin.

## Model detail

Click a card to open the model. From here you can:

- View and switch between all its preview images.
- Toggle to the **3D viewer** (if it has STL files).
- **Edit tags inline** — click the **+** button next to a tag to add a tag, or
  the **×** on any tag to remove it, without opening the full edit screen. The
  tag list autocompletes from all tags already in your library.
- Edit metadata, tags, source URL, and the NSFW flag (full form via **Edit**).
- See and label each STL file (head, arm, base, etc.).
- **Download all** files as a zip, or open the **Kit Builder**.
- Add the model to one or more **Collections** (see below).
- See the model's **Location** on disk — copy the path, or (standalone only)
  click **Open folder** to jump to it in your file manager.
- An **unorganized** icon appears next to the title if the model's current
  folder no longer matches where [Reorganize](#reorganize-library) would put
  it (e.g. after changing its creator or title) — hover it for a tooltip.
  Nothing moves automatically; run Reorganize to actually move it.

### File parts, sup variants & label naming

Each STL file can be labeled with a **part type** (head, arm, base…) and an
editable **Name**. The Name is filled in automatically from the filename the
first time a file is scanned (see [scanning](scanning-and-folders.md#stl-file-part-names))
— editing it or applying an AI Organize suggestion always overrides that
default for good, a later rescan never resets it. A part can have multiple **sup variants** — alternate
supported/cut versions of the same part (`s1`, `s2`, …) — and the part picker
renders one button per sup variant so you can switch which cut you're viewing
without hunting through the file list. Selecting a row in the file list and
the corresponding button in the part picker stay in sync in both directions,
auto-unfolding collapsed sections as needed. Changing a part's category
applies to every file linked to it (the base file and all its sups).

Clicking the link icon to attach a sup opens a searchable picker: it lists
each candidate by its **part name** (falling back to the filename if a file
has none set) with the filename shown underneath for reference, and typing
filters the list by either — much faster than scanning a plain dropdown of
raw filenames on a kit with dozens of parts.

The **part type** field is a combobox: start typing to filter a list of
standard suggestions plus any custom category already used somewhere on this
model (listed alphabetically together — the same combined list the bulk
**Recategorize to…** dropdown offers), or type a brand new category name. The
dropdown appears automatically, opening above the field instead of below when
there isn't room underneath, and can be dismissed with Escape; pressing Enter
or clicking away commits the value.

**Settings → Preferences → Horizontal parts layout** (on by default) swaps the
two-column model detail page for a full-width, scrollable files table below the
main grid (with **Collections**, **Location**, and **Other Files** moved into the
right column) — handy for models with a lot of parts. The part picker is hidden
in this mode since the table serves the same purpose. Checking one or more rows
shows a **Recategorize to…** dropdown in the toolbar (next to Download
selected) — offering the standard category suggestions plus any custom
category already used on this model — so you can move several files into a
category in one action instead of editing each row's Category field by hand.

Files and categories in both layouts sort numerically where a name has an
embedded number, so "Body 2" sorts before "Body 10" instead of after it.

**Settings → Preferences → Enable part categories** turns on the Category field
on each file in the model detail view. Files group into collapsible sections and
the 3D viewer organises its part picker by category — useful for complex
multi-part kits.

**Other Files** lists a model's non-STL, non-image files (PDFs, datapackage.json,
etc.) — click one to download it. Each entry has a delete icon that removes it
both from disk and from the listing (with a confirmation first); if the file was
already gone from disk (e.g. deleted outside the app), this still clears the
stale listing.

**AI Organize** (button on the model detail page) suggests a category and
cleaned-up name for every STL file, or links supported variants to their base
part. Clicking it first asks you to pick a strategy:

- **Parts-based** — the standard approach. Requires an AI API assigned under
  [Settings → AI & Integrations](#ai--integrations). Fast keyword-based naming
  rules run first, but the AI always runs too — even on files the naming rules
  already resolved — since it can still catch a wrong guess or a name the
  rules got half right. It only ever picks from the app's standard category
  list, so its suggestions land in the same categories the Category combobox
  offers.
- **Unit-based** — requires an AI API. Groups files by the in-game unit or
  character they belong to instead of by physical part (e.g. every file for
  "Royal Guard 1" — head, helmet, weapon — gets that as its category, not
  "Head"/"Weapon"). There's no keyword pre-pass for this — it goes straight to
  the AI. Unit names are derived per model, so they aren't limited to the
  standard category list; each one is title-cased for consistency across a
  unit's files. Large kits are sent to the AI in small batches (5 files at a
  time) rather than one capped call, so every file gets a suggestion, not just
  the first several — later batches are told which unit names earlier ones
  already settled on, so the same unit isn't renamed partway through a big kit.
- **Link supported parts** — no AI API needed; this is pure name matching, not
  an AI call. Finds every file whose filename (or, failing that, its part
  name) contains "Sup", "Supported", or "Hollowed" and isn't already linked to
  a base, and matches it to a same-named plain file — e.g.
  "icon-of-flame-2-supported.stl" links to "icon-of-flame-2.stl". Matching
  goes by filename first specifically because part names can drift or get
  mislabeled independently of the file (two different parts ending up with
  the same, wrong, part name is a real thing that happens); part name is only
  a fallback for a file matched with no useful filename signal. A file without
  one of the keywords is only ever a possible match target, never linked to
  another file itself, so it's safe to run on a whole kit without relabeling
  anything that's already named correctly. An already-linked file is never
  touched or re-matched.

On a local model via an OpenAI-compatible endpoint (Ollama, etc.), requests use
schema-constrained output and an explicit instruction against extended
reasoning — local "thinking"-style models can otherwise spend their whole
response budget on hidden reasoning and never produce an answer, or drift
into inventing their own JSON shape instead of the one requested. A reply
that's almost-but-not-quite valid JSON (a stray trailing comma, prose wrapped
around an otherwise-good object) gets one best-effort repair attempt before
being treated as a failure.

Either way, review the suggestions in a modal before applying — nothing is
written to a file until you confirm.

## 3D viewer

On any model with STL files, switch to **3D View** to inspect the mesh:

- Drag to rotate freely in any direction, scroll to zoom, right-drag to pan.
- The camera auto-fits the model on load, so it's framed correctly every time.
- If a model has several STLs, use the file buttons to switch which one you're
  viewing.
- A size warning appears for very large files (they can be slow to load in a
  browser).

## Image picker (thumbnails)

If the auto-chosen thumbnail is wrong (or missing), open a model and click
**Change image** on the preview. The **Set Thumbnail** dialog offers:

- **From Folder** — every image found in that model's own folder, to pick from.
- **From URL** — paste any image URL; the image is downloaded and stored
  locally, so it keeps working even when the site blocks hot-linking.
- **Upload** — pick a PNG, JPEG, WebP, or GIF from your computer (max 15 MB);
  it's applied as the thumbnail immediately.
- **Clear** — remove the thumbnail entirely.

To clear an image quickly without opening the dialog, use **Clear image** in a
card's **⋯ quick-assign** menu, or the **Clear image** button next to **Change
image** on the model's detail page.

## Favorites, print queue & printed tracking

Three independent ways to organize what you want to print. A model can be any
combination of these.

- **★ Favorite** — bookmark models you love. Filter the Library to favorites
  with the header chip.
- **🖨 Queue** — add models to your print queue. The **Queue** page (in the top
  nav) shows everything queued so you have a running "to print" list, and the nav
  shows a live count badge. **Drag the handle** (bottom-left of each card) to set
  your own print order; **favorites always float to the top**.
- **✓ Printed** — mark a model as printed. This records the date and removes it
  from the active queue. The Queue page keeps a **Recently Printed** section so
  you can see what you've finished, and the Library has a **printed** header chip
  to filter down to everything you've printed. If you mark something printed by
  mistake, click **Undo printed** in the model header to revert it to not-printed
  (the print date is cleared).

You can toggle favorite/queue right from a card (hover icons) or from the
buttons in a model's header. *(Printed* is set from the model header.)

## Kit Builder

Launched from any model's detail page. It groups that model's STL files by their
**part label** (head, torso, arms, base…). Click any file to toggle it into
your selection — any number of files can be selected at once, independently of
each other — then copy the file list or download the selection as a zip. Handy
when a model ships multiple head or pose options and you want to commit to a
combination, or when you want to grab several parts from one category at once.

The Kit Builder uses a two-panel layout:

- **Left panel** — the part selector. Files are grouped by label; click any
  file to toggle it in your selection — nothing is exclusive, so a part and
  its own linked variants (see below) can all be selected together, or any
  combination of files across different parts.
- **Right panel** — a live 3D preview pane. Hover any part button to instantly
  load it in the viewer without affecting your selection. The pane stays pinned
  to the right side even as you scroll through a long parts list.

**Linked variants** (a part with a supported/hollowed/other version linked via
its [sup relationship](#model-detail)) render as one box instead of a separate
pill per file: the base part on top, with each linked variant as a smaller row
below it, labeled **Supported**, **Hollowed**, or **Other** by name-keyword
match. Click any row — base or variant — to toggle just that one file.

To make this useful, label your parts first: on the model detail page, each STL
file has a small **Label** input with common suggestions.

## Metadata editing & web enrichment

Open a model and click **Edit** to change the title, creator, description,
notes, source URL, license, category, tags, and NSFW flag.

The **Source URL** field has a **Fetch** button: paste a product page from
**Gumroad**, **Cults3D**, **MyMiniFactory**, or **Loot Studios** and it scrapes
the page to fill in the title, description, creator, thumbnail, and tags
automatically.

There's also bulk enrichment from the **Creators** page (see below).

## Triage queue

A keyboard-driven review screen at **/triage** for models the scanner flagged as
uncertain (`needs_review`). Work through them quickly:

- `→` / **Space** = dismiss (looks fine)
- `S` = skip
- `←` = go back

The nav shows a live count of how many models still need review.

## Collections

**Collections** let you group models into named sets — independent of tags or
creators. Use them for things like "Army project", "Current print queue", or
"Gift ideas".

### Collections page (`/collections`)

Each collection card displays its cover image (if set), name, a truncated
description (hover for the full text), and model count.

- **Create** a collection with the **New Collection** button — a dialog asks
  for a name and optional description, then immediately offers the cover-image
  picker (URL, upload, or from one of the collection's models once you've
  added some) so a new collection can be fully set up in one step.
- **Edit name & description** — hover the card and click the pencil icon. The
  form shows a name field and a scrollable multi-line description box; press
  **Save** or click **Cancel**. Clearing the description removes it.
- **Set a cover image** — hover the card and click the image icon. Three options
  are available in the picker:
  - **URL** — paste a direct image link. The image is fetched server-side, so
    CDN hot-link blocking is not an issue.
  - **Upload** — pick a PNG, JPEG, WebP, or GIF from your computer (max 15 MB).
  - **From model** — a grid of the collection's models; click any thumbnail to
    use it as the cover. Use **Remove cover** at the bottom of the picker to
    clear a cover that's already set.
- **Delete** a collection — hover the card and click the trash icon, then
  confirm. Deleting a collection does not delete any models; it only removes the
  grouping. The cover image file is also deleted.
- Click a collection card to open its **detail view**.

### Collection detail view

Shows every model in the collection as a standard grid. To **remove** a model
from the collection, hover the card and click the **×** button in the top-left
corner.

### Adding models to a collection

There are two ways:

1. **From a model's detail page** — scroll to the **Collections** section in
   the right column and click **Manage**. A checkbox list appears; tick any
   collection to add the model to it (untick to remove). You can also create a
   new collection inline from the same panel — it's created and the model is
   added in one step.

2. **Bulk add from the Library** — select multiple models using their hover
   checkboxes, then click **Add to Collection** in the floating bar at the
   bottom of the screen. Pick a collection from the list that appears.

### Notes

- A model can belong to any number of collections.
- Collections are included in the database backup, so they survive a
  backup/restore with no extra work.

## Bulk editor (tags & enrich)

In the Library, hover a card and use the checkbox to select multiple models. A
floating bar appears with bulk actions across the whole selection at once:

- **Add or remove tags** — apply or strip a tag on every selected model.
- **Add to a collection** — drop the whole selection into a collection.
- **Enrich** — set **creator**, **character**, and/or **title** across the
  selection in one pass. Leave a field blank to leave it untouched. This is the
  fast way to fill in metadata for loose or badly-named imports so they become
  eligible for [Reorganize](#reorganize-library).

## Import folder

**Import** (in the nav, at **/import**) brings an arbitrary folder of loose
downloads, an unzipped pack, or a pile of unsorted files into the catalog
**without** adding it as a permanent scan root — then files them into a managed
library on disk. It implements the full **import → enrich → organize** pipeline.

### Libraries (the import destination)

A **library** is a scan root you've named and marked as an **import
destination** (Settings → a folder card → set a **Library** name and tick
**Import destination**). Only writable libraries can receive imported files —
see [Scanning & folders](scanning-and-folders.md#libraries-import-destinations).

### The flow

1. **Pick a source folder** at **/import** → **Preview packs**. This opens the
   **Import Preview** screen (`/import/preview`).
2. **One card per pack** — each immediate subfolder of the source is a pack card
   (files directly in the source form a single pack).
3. **Choose the destination Library** once from the dropdown. The choice is
   saved as a **source → library mapping**: every pack under that source inherits
   it, and the dropdown pre-fills (but stays editable) next time.
4. **Enrich each pack** — expand a card to set **Creator, Character, Title, and
   Tags**, or paste a **Source URL** and click **Fetch** to pull title, creator,
   tags, and gallery images from a Gumroad/Cults3D/MyMiniFactory product page
   (the store — `source_site` — is recorded too). Then click **Import**. That
   ingests just that pack's folder as inbox models, downloads any fetched
   gallery images into the pack folder (concurrently, so a slow/unreachable
   image doesn't block the rest), applies the metadata, and immediately moves
   that pack into the destination library on disk (drift-checked, with undo)
   — no separate move step. The **inbox** flag clears as the pack lands, and a
   progress bar shows what's happening at each stage (downloading images,
   then moving files).
5. **"Move N imported packs → {library}"** — a batch bar for moving every
   already-ingested-but-not-yet-moved pack under the current source in one go
   (e.g. after a Quick import).

### Notes

- **Quick import (whole folder)** on `/import` keeps the original one-shot index
  of the entire source in a single pass (each immediate subdir = a creator,
  loose files → an `_Inbox` creator) — handy when you don't need per-pack review.
- **Inbox flag** — un-filed imports are marked **inbox**; the Library's
  `?is_inbox=1` filter shows just these.
- The **move** step follows the Reorganize page's slug-formatting setting
  (**Settings → Library**) — with it on, an imported pack's creator/title
  segments land already lowercase-and-hyphenated on disk, with no separate
  manual Reorganize pass needed afterward.
- The **move** step requires the **Reorganize Library** feature flag (**Settings →
  Library**, off by default) and a writable destination — Docker mounts are
  read-only, so moves are effectively standalone-only. Importing and enriching
  work everywhere. Packs missing a creator/character (or otherwise blocked) are
  reported as skipped, not moved.

## Creators & per-creator rescan

The **Creators** page lists every creator with their model count. From here you
can:

- **Add Creator** — add a creator manually, before you've imported any of
  their models. Its library folder is created automatically (using the
  [Reorganize](#reorganize-library) destination template) so it's ready for
  files to land in.
- Click a creator to browse just their models in the Library.
- **Rescan** a single creator — a targeted scan of just that creator's folder.
  Because you usually add models one creator at a time, this is much faster than
  a full library scan. The button is disabled while any scan is running.
- **Enrich from web** — match a creator's online storefront listings against
  your local models, then fetch each matched product's **full detail** and
  bulk-apply the complete metadata set: title, description, tags, category,
  license, thumbnail, source URL, and external ID. One run enriches every
  matched model — including all variants in a group — so you no longer have to
  open each model and run *Find on Web* by hand. Expand any match (the chevron)
  to preview the description, tags, category, and license it would apply before
  committing. MyMiniFactory and Cults3D use their APIs when configured (see
  [Settings → AI & Integrations](#settings)); Gumroad is scraped. A product whose detail can't be fetched still receives the
  shallow fields, so nothing is lost.

## Paint Shelf (Painting Guides)

The **Paint Shelf** is always available in the nav — it's standalone paint
inventory and doesn't require the guides feature. Enabling **Settings →
Painting Guides** additionally adds the **Guides** entry (authoring and reading
step-by-step painting guides).

The **Paint Shelf** is a table of every paint you own (or want): search by name
or code, filter by brand, line, finish, or owned state, and see a **color
chip** for any paint with a swatch color set. Add or edit paints inline with
the **Add paint** form.

A paint line can declare a **code pattern** (a regex like `^MPA-\d{3}$`); paint
codes are then validated on entry, so typos like `MPA-12` get caught with a
clear message instead of polluting the shelf.

### PaintRack CSV import & export

The Paint Shelf's import/export uses the CSV format from
[**PaintRack**](https://www.courageousoctopus.com/) by Courageous Octopus — a
great paint-inventory app. STL Studio isn't affiliated with it; we just
interoperate with its export so you can reuse a shelf you've already built.

If you track paints in **PaintRack**, import its CSV export directly:

- **Import CSV** shows a **diff preview** first — what would be added, changed,
  or removed — and writes nothing until you confirm. Removals are off by
  default behind a separate checkbox, and only ever touch paints that came from
  a previous import; paints you added by hand are never deleted.
- Codes that don't match a line's code pattern are listed as **warnings** in
  the preview — informational only, the rows still import.
- **Export CSV** downloads your shelf in the same format, and an export
  re-imports as an empty diff (a lossless round-trip).

### Swatch colors in the CSV

The CSV has an optional seventh **Color** column so an import can pre-populate
swatch colors, and your stored swatches are included in every export:

| Format | Example |
|--------|---------|
| Hex | `#2A2A2A` |
| RGB | `"rgb(176,48,48)"` |
| HSV | `"hsv(120,50,80)"` (H 0–360, S/V 0–100) |

All three are normalized to hex on import. Because `rgb()`/`hsv()` values
contain commas, those cells must be **quoted** in the CSV. Files without the
column (like real PaintRack exports) import exactly as before, and an **empty
color cell never clears** a swatch you've already set — only a different,
non-empty color shows up as a change in the preview.

### Color-match studio

The **Color match** button on the Paint Shelf opens a studio that suggests
paints from your shelf to match a reference photo (a render, box art, or a
painted mini).

- **Value-first.** For each sampled color you get a **Value ladder** — a
  **shadow → mid → highlight** ramp in the same hue family, anchored on the
  sampled mid-tone (Dark Camo Green → Green → Bright Yellow-Green) so the steps
  read as a cohesive recipe — then a **Hue match** (opaque paints ranked by
  ΔE2000), and a labelled **Glaze / wash** list for transparents. Every
  suggestion carries a confidence band (*very close*, *confirm*, *family*,
  *loose*) — suggestions to **confirm by eye**, never auto-applied.
- **Eyedropper.** Click anywhere on the preview to match that exact spot —
  sample the skin, then the hair, then the leather, each with its own
  suggestions. The **Palette overview** below is an automatic read of the whole
  image, with the background excluded so the subject leads.
- **Value mode** (on by default) greys the swatches so you can read values; turn
  it off to compare hues in color.
- Large photos are downscaled in the browser before upload, so even a phone shot
  uploads instantly.

### Painting guides

The **Guides** page lists your painting guides; open one to read it in-app. A
guide is a tabbed, step-by-step recipe: per-tab **value maps**, numbered
**steps** with technique tags, **paint swatches** drawn from your Paint Shelf
(every guide only references paints you own), method cards, and a shared
**Thinning Reference**. Each guide carries its own theme, so it looks the same
as the standalone HTML version.

- **New guide** (button, top-right of the Guides page) creates a guide from
  scratch, and **Edit** (button, top-right of an open guide) changes its title,
  subtitle, scale, franchise, technique tags, creator credit, paint lines and
  other header details. **Edit content** (button, top-right of an open guide)
  opens a structured editor for the guide's tabs, phases, steps and paint
  swatches — add, remove and reorder each level, and pick swatch paints from your
  shelf. Saving content replaces the guide's tab tree; saving metadata leaves the
  content untouched.
- **Mix swatches** — a step swatch can reference a blend like *"Paint A + Paint B
  (3:1)"*. These import from guide HTML, render as a single blended-dot chip in
  the reader, and round-trip cleanly back to the same notation on export.
- **Import guide** (button, top-right of the Guides page) uploads a guide HTML
  file — click the file input, or **drag and drop** an `.html` file onto the
  dropzone. It lands as a **draft** for review — never auto-published — and shows
  an **import report**: how many swatch paints matched your Paint Shelf and any
  content the importer couldn't map.
  - If some paints didn't resolve, the importer shows a **Paint resolution**
    step before committing. For each unresolved paint you can: **Map** it to an
    existing shelf paint, **Force-add** it straight to your Paint Shelf
    (pre-filled with any swatch color from the guide), or **Skip** it (the swatch
    is dropped). Once every paint is resolved or skipped, the guide imports.
  - Add missing paints to your Paint Shelf before importing if you'd rather not
    use the resolution step, or just re-import after the shelf is updated.
- **Validation panel + publish gate.** While editing, a validation panel lists
  problems grouped by severity, each linking to the exact step. **Blocking**
  issues (a swatch paint you don't own, or a code that fails its line's pattern)
  must be fixed before you can publish — trying to publish with a blocking issue
  is rejected. **Warnings** (an empty tab, a step with no swatches, value numbers
  that barely differ) are advisory and don't block.
- **Theming.** Each guide carries its own colour theme, editable in the guide
  editor's **Theme** section: colour pickers for background, surfaces, borders,
  text and accent, plus a hero-gradient field, with a live mini-preview. Leave a
  field blank to inherit the **default guide theme** you set under
  **Settings → Painting Guides → Default guide theme**, which every new guide
  starts from. Themes apply in the in-app reader and the exported PDF; a guide's
  raw `head_style` (from imported guides) still wins as an escape hatch.
- **Publish / Unpublish** and **Delete** (buttons, top-right of a guide) control
  a guide's lifecycle: drafts stay flagged in the list until you publish, and
  delete removes the guide and all its tabs, steps and swatches after a
  confirmation.
- **Print** (button, top-right of a guide) expands *every* tab and sub-tab into
  one continuous, print-styled document — the whole guide in one pass. The print
  stylesheet preserves dark backgrounds and paint chip colors (`print-color-adjust: exact`)
  so swatches render correctly on paper and in PDF.
- **Export PDF** (the export menu, top-right of a guide) renders that same
  print-styled document to a downloadable PDF. The menu carries per-export
  **reward-stamping** options: a **Patreon-exclusive footer** (on by default),
  an optional **tier label**, and a **watermark** (off by default). If the guide
  belongs to a **series**, **Export series bundle** renders every published guide
  in that series into one PDF, with an optional **cover page**. In Docker the
  renderer is bundled and ready to use; the standalone build needs a one-time
  `playwright install chromium` (see the install notes) the first time you export.
- **Model links** tie guides to your library both ways: a model that has a guide
  shows a **Guide** badge on its Library card and a **Painting guide** button on
  its detail page, and the guide links back to its model.

## Reorganize library

**Settings → Library Tools → Reorganize Library** (or **/reorganize**) tidies your
files on disk to match a folder template — by default
`{creator}/{character}/{title}`.

Destination templates support `{creator}`, `{character}`, `{scale}`, and
`{title}`. `{scale}` comes from scanner-detected scale auto-tags such as `1:6`
or `75mm`; if a template uses `{scale}` and a model has no detected scale, that
row is marked unclassifiable until you resolve it.

The destination template and a **"Lowercase, hyphenated directory names"**
toggle live in **Settings → Library → Reorganize** — both are saved server-side,
so they're shared with manual [creator](#creators--per-creator-rescan) folder
creation and the model detail [unorganized indicator](#model-detail), not just
this page. The toggle is on by default: every segment renders slug-style (e.g.
`abe-3d` instead of `Abe 3D`), matching how imported folders are named. Turn it
off to keep each segment's original casing and spacing.

- **Preview first.** The page shows exactly where every model *would* move, one row
  each, with a move-kind chip (move / rename / case rename / in place / merge) and
  blocker chips for anything unsafe (collision, over-length or reserved name,
  unclassifiable, symlink, multi-directory, escapes-scan-root, missing files).
  Nothing is touched until you apply. A **missing files** chip means the app's
  own record of that file's path doesn't resolve on disk — usually because it
  was renamed or moved outside the app. A full [scan](scanning-and-folders.md#full-scan-vs-per-creator-rescan)
  cleans up file records left behind by an out-of-app rename; run one before
  trusting a persistent "missing files" chip.
- **Resolve flagged rows.** Expand an ineligible row to supply a missing
  creator/character/title or add a suffix that breaks a collision or shortens an
  over-long/reserved name. The preview regenerates as you type.
- **Apply.** Tick the eligible rows and **Apply**. The app verifies each file
  hasn't changed since the preview (aborting the whole batch on any drift), moves
  files safely across drives, and repaths the index — packs and manual character
  groupings are carried along, not orphaned. A model's own gallery images
  (thumbnail, library card image, and the rest of the gallery) move right
  along with its STL files — only images inherited from a shared parent
  folder (e.g. a character-level "renders/" dir also used by sibling
  variants) are left in place, since moving those would break the path for
  the other models still pointing at them. Once every tracked file has moved
  out, the now-empty source folder is removed. If one of a model's tracked
  images collides with an unrelated file already sitting at the destination
  (e.g. leftover marketing art bundled with a download, or debris from an
  earlier interrupted apply), that one image is skipped — logged, left where
  it is — rather than failing the whole batch; an STL file collision still
  aborts the batch exactly as before, since a wrong or missing STL is a real
  problem, not an incidental extra image.
- **Undo.** **Undo last apply** reverses the batch, skipping anything you've since
  edited or that now sits where a file would return.

Apply moves real files, so it is **opt-in**: it stays disabled unless the
**Reorganize Library** feature flag is turned on under **Settings → Library**
(off by default) and the destination is actually writable (the read-only Docker
mount can never apply, making apply effectively standalone-only). Preview and
resolve work everywhere.

## Settings

At **/settings** you manage your **scan roots** — the top-level folder paths the
app reads from. Add or remove paths, and see when each was last scanned. This is
also where standalone users point the app at their drives for the first time.

If a configured folder can't be found when the Library loads — typically an
external drive that's unmounted or disconnected — a warning banner appears at the
top of the Library listing the affected paths, so an empty library reads as
"drive unavailable" rather than "everything is gone".

It's also home to **Scan Rules** and **Data Management** (see below).

## AI & Integrations

**Settings → AI & Integrations** has three sections.

### AI APIs

A list of named AI API connections. Add as many as you need — different
models, local Ollama instances, or separate keys for different purposes. Each
entry has:

- **Name** — a human-readable label used to identify it in the AI Functions
  selectors below (e.g. "Ollama Local", "Anthropic Creative").
- **Type** — `Anthropic` or `OpenAI-compatible` (covers Ollama, LM Studio,
  and any OpenAI-API-compatible endpoint).
- **Model** — for Anthropic, a dropdown of supported Claude models; for
  OpenAI-compatible, the app fetches the available model list from the base
  URL automatically when you enter it.
- **Effort** — (Anthropic only) controls reasoning depth: Low, Medium, or High.
- **Timeout** — how long (in seconds) to wait for a response from this
  endpoint before giving up. Defaults to **10s**, which suits a local Ollama.
  A **remote** Ollama loading a model for the first time (a "cold start") can
  take much longer, especially for a large model on modest hardware, so raise
  this for remote endpoints — up to **600s** (10 minutes). The setting is
  per-connection, so a fast local API and a slow remote one can each have
  their own value.
- **API key** — stored encrypted server-side, using a separate encryption key
  (`STL_SECRET_KEY`, see [Docker configuration](docker.md#optional-environment-variables))
  so a leaked database alone doesn't expose it. For Ollama and similar local
  endpoints, a key is optional. Entered alongside the other fields and saved
  together with **Add API**/**Save changes** — there's no separate save step
  for the key. On the Windows Electron build this key is generated and managed
  automatically — see the note in [Docker configuration](docker.md#optional-environment-variables).

You can add multiple entries of the same type — for example, two Anthropic
entries using different models for different tasks, or both a local Ollama
instance and a remote OpenAI-compatible endpoint.

### AI Functions

Controls which AI features are active and which named API each one uses.

- **AI Guide Drafts** — when enabled, an AI generates a first-draft painting
  guide for review before saving. Choose which configured API to use.
- **AI Naming & Organizing** — when enabled, normalizes part names, assigns
  categories, and links presupported files on a per-model basis. Choose which
  configured API to use. Internally, fast built-in heuristics run first and
  handle well-named files on their own — the AI is only called for files the
  heuristics can't classify. But the review modal only ever shows suggestions
  the AI actually produced: it's **success via the API, or nothing** — a
  heuristic guess is never presented as if the AI made it. If every file was
  already unambiguous, if the AI call failed, or if no API is configured yet,
  the modal opens with a clear explanation instead of any rows to review — see
  [Logging](#logging) to inspect the details of a failed call.

> Works with either an **OpenAI-compatible API** (e.g. Ollama) or an
> **Anthropic** connection — assign one under **AI APIs**, then select it here.
> If a remote endpoint is slow to respond, raise that connection's **Timeout**
> (see AI APIs above).

### Metadata

Third-party integrations that enrich your library with creator details,
metadata, and thumbnails.

- **Cults3D** — connect with a Cults3D username + API key. API access is
  gated; request it in `#api-help` on the Cults3D Discord. Credentials are
  stored encrypted.
- **MyMiniFactory** — add a MyMiniFactory API key (register an app under
  MyMiniFactory Settings → Developer). Stored encrypted.

When configured, these APIs are used automatically during
[web enrichment](#metadata-editing--web-enrichment).

## Logging

**Settings → Preferences → Logging** sets how much the backend writes to its
output. Pick one of the five standard levels — `DEBUG`, `INFO` (the default),
`WARNING`, `ERROR`, `CRITICAL`. The change **takes effect immediately, without a
restart**, and persists across restarts.

- `INFO` — normal operation. Includes a one-line-per-step trace of AI calls
  (endpoint, model, timeout, elapsed time, HTTP status, outcome).
- `DEBUG` — everything in `INFO` plus verbose detail, including the raw response
  body returned by the AI endpoint. Useful when diagnosing why an AI call
  behaves unexpectedly.
- `WARNING` and above — quieter; only problems (failed/timed-out AI calls, etc.)
  are logged.

**Viewing the logs** depends on how you run the app. Under Docker:

```bash
docker compose logs -f backend
```

The initial level can also be set at startup with the `LOG_LEVEL` environment
variable (see [Docker configuration](docker.md)); a value chosen in the UI
overrides it and is what survives restarts.

## Scan rules

Under **Settings → Scan Rules** you can tune how the scanner reads your folders.
Each list *adds* to the built-in behaviour — you extend the defaults, you can't
break them. All three take effect on the next scan.

- **Ignore patterns** — folders matching a pattern (and everything inside them)
  are skipped. Matching is case-insensitive against a folder's name (`WIP`) or its
  full path (`*/_archive/*`). Adding a pattern also drops any already-indexed
  models it now covers on the next scan.
- **Tag rules** — a keyword→tag pair adds an auto-tag to any model whose name
  contains the whole keyword (e.g. `Aztec` → `civ`). They supplement the built-in
  tag detection and do **not** change how variants group.
- **Parts folder names** — exact folder names (e.g. `Sprues`, `Magnets`) treated
  as parts/structure: never indexed as their own model and never used to group
  variants, alongside the built-ins (Parts, Base, Supports…).

A safety cap protects against an over-broad ignore pattern: if a single scan
would remove more than half your models, the cleanup is skipped and logged.

## Backup, restore, repair & reset

At the bottom of **Settings**, under **Data Management**, you can manage the
library database itself. This only ever touches the *index* — your metadata,
tags, favorites, and print queue. **Your STL files on disk are
never modified.**

- **Download Backup** — saves a consistent snapshot of your whole library as a
  `.db` file (named with a timestamp). Keep this somewhere safe; it's the only
  way to recover your tags, favorites, and queue if something goes wrong.
- **Check Health** - runs SQLite's integrity check against the live database
  without changing it.
- **Repair Database** - snapshots the database, runs a conservative SQLite
  `REINDEX`, and verifies integrity again. This can fix index-only corruption;
  deeper table corruption still requires restoring a clean backup or manual
  recovery.
- **Restore from Backup…** — pick a previously downloaded `.db` file to replace
  your current library with it. The file is validated first (it must be a real
  STL Studio backup), and an older backup's schema is brought up to date
  automatically.
- **Delete All Data** — wipes the entire index back to empty. You'd then run a
  full scan to rebuild it.

Repair, Restore, and Delete require a confirmation phrase because they can modify
or replace the index. Download a backup before using them. (They cannot run while
a scan is in progress.)

## NSFW toggle

A global **NSFW On/Off** switch in the top-right of the nav. When off, models
flagged NSFW are blurred in the grid and detail view. You can flag/unflag any
model from its card or detail header, and filter by NSFW status in the Library.
