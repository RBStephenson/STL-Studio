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
- [Bulk tag editor](#bulk-tag-editor)
- [Creators & per-creator rescan](#creators--per-creator-rescan)
- [Settings](#settings)
- [Backup, restore & reset](#backup-restore--reset)
- [NSFW toggle](#nsfw-toggle)

---

## Library

The main grid. Every filter lives in the URL, so you can bookmark or share a
filtered view.

- **Search** by name, title, description, or character.
- **Filters:** creator, source site, tag, NSFW, has-image, needs-review,
  favorites, in-queue, and printed. Open the **Filters** panel for the full set,
  or use the quick chips in the header (e.g. "*N* favorites", "*N* queued",
  "*N* printed") — so you can see both what you want to print and what you've
  already printed.
- **Saved presets:** once you've dialed in a set of filters, save it as a named
  preset (stored in your browser) and re-apply it with one click.
- **Pagination:** Prev / page number / Next, with a jump-to-page box — shown at
  both the top and bottom of the grid so you can page without scrolling.

Each card shows the thumbnail, name, tags, and small action icons (favorite ★
and print-queue 🖨) that appear on hover. You can also **drag a card by its
hover grip onto another card to group them as variants** — see
[Variant grouping](#variant-grouping).

## Variant grouping

When several folders share the same character (for example a *Bust*, a
*Full size*, and a *Pre-supported* version of the same figure), the Library
collapses them into a **single group card** with a "*N* variants" badge.
Click it to open the group and see each variant individually.

This keeps the grid tidy when a creator ships many cuts/versions of one model.

### Fixing mis-grouped models

The scanner infers the character group from folder names — it's accurate for
most layouts but occasionally gets it wrong (typo'd folder, unusual nesting,
inconsistent studio naming). You can fix any mis-grouping durably, so your
correction survives future rescans:

**Drag-to-group from the Library** (fastest for grouping loose models)

In the main Library view, hover a model card and a small **grip handle**
appears in its bottom-left corner. Drag the card onto another card from the
**same creator** to group them. A naming prompt opens, pre-filled with the
target's existing group name (if it already belongs to one) or otherwise its
display name — confirm or edit the name, and both models are placed in that
group. (The prompt always appears so you can rename or back out, even when the
target is already grouped.)

Grouping only works within a single creator, and only in the default Library
view (it's off in the favorites/queue/printed/excluded views, which show flat
cards). Group cards themselves can be dropped onto but not dragged.

**From the group view** (fastest for fixing a whole group at once)

Open a group card to see all its variants. Below each card there are two
quick actions:

- **Move to group** — type the target group name. As you type, a dropdown
  offers the creator's existing groups so you don't have to remember exact
  names. Press **Enter** or click **Move** to apply; the variant is removed
  from the current list immediately.
- **× Remove** — pull the model out of this group entirely, making it a
  standalone model in the Library.

**From a model's detail page**

Click a model, then find the **Set group** button in the header (alongside
*Edit*, *Find on Web*, and *Split pack*):

- Click **Set group** to open an inline input. Start typing — existing groups
  for that creator appear as suggestions so you can pick from a list rather
  than type the full name from memory. Leave the field blank and save to
  **ungroup** the model. Press **Enter** or click **Save**; press **Escape** to
  cancel.
- Once an override is active, the button changes to an indigo **Group: [name]**
  chip. Click it to change the assignment, or click **✕** beside it to clear
  the override (restoring scanner-detected grouping on the next rescan).

**How overrides work**

A group override is written to the database and applied immediately — the
model moves to the new group without needing a rescan. On every future rescan
the scanner sees the override and applies it instead of the heuristic, so your
corrections are permanent. Clearing an override removes the record; the scanner
will re-derive the group on the next rescan.

## Model detail

Click a card to open the model. From here you can:

- View and switch between all its preview images.
- Toggle to the **3D viewer** (if it has STL files).
- Edit metadata, tags, source URL, and the NSFW flag.
- See and label each STL file (head, arm, base, etc.).
- **Download all** files as a zip, or open the **Kit Builder**.
- Add the model to one or more **Collections** (see below).
- See the model's **Location** on disk — copy the path, or (standalone only)
  click **Open folder** to jump to it in your file manager.

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
- **From URL** — paste any image URL to use instead.
- **Clear** — remove the thumbnail entirely.

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
  to filter down to everything you've printed.

You can toggle favorite/queue right from a card (hover icons) or from the
buttons in a model's header. *(Printed* is set from the model header.)

## Kit Builder

Launched from any model's detail page. It groups that model's STL files by their
**part label** (head, torso, arms, base…). Pick one file per part group to
assemble a complete build, then copy the file list or download the selection as
a zip. Handy when a model ships multiple head or pose options and you want to
commit to one combination.

To make this useful, label your parts first: on the model detail page, each STL
file has a small **Label** input with common suggestions.

## Metadata editing & web enrichment

Open a model and click **Edit** to change the title, creator, description,
notes, source URL, license, category, tags, and NSFW flag.

The **Source URL** field has a **Fetch** button: paste a product page from
**Gumroad**, **Cults3D**, or **MyMiniFactory** and it scrapes the page to fill
in the title, description, creator, thumbnail, and tags automatically.

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

- **Create** a collection with the **New Collection** button.
- **Rename** a collection — hover the card and click the pencil icon, then type
  a new name and press Enter (or click **Save**).
- **Delete** a collection — hover the card and click the trash icon, then
  confirm. Deleting a collection does not delete any models; it only removes the
  grouping.
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

## Bulk tag editor

In the Library, hover a card and use the checkbox to select multiple models. A
floating bar appears where you can **add or remove tags** or **add to a
collection** across the whole selection at once.

## Creators & per-creator rescan

The **Creators** page lists every creator with their model count. From here you
can:

- Click a creator to browse just their models in the Library.
- **Rescan** a single creator — a targeted scan of just that creator's folder.
  Because you usually add models one creator at a time, this is much faster than
  a full library scan. The button is disabled while any scan is running.
- **Enrich from web** — match a creator's online storefront listings against
  your local models and bulk-apply metadata (source URLs, thumbnails, IDs).

## Settings

At **/settings** you manage your **scan roots** — the top-level folder paths the
app reads from. Add or remove paths, and see when each was last scanned. This is
also where standalone users point the app at their drives for the first time.

It's also home to **Data Management** (see below).

## Backup, restore & reset

At the bottom of **Settings**, under **Data Management**, you can manage the
library database itself. This only ever touches the *index* — your metadata,
tags, favorites, and print queue. **Your STL files on disk are
never modified.**

- **Download Backup** — saves a consistent snapshot of your whole library as a
  `.db` file (named with a timestamp). Keep this somewhere safe; it's the only
  way to recover your tags, favorites, and queue if something goes wrong.
- **Restore from Backup…** — pick a previously downloaded `.db` file to replace
  your current library with it. The file is validated first (it must be a real
  STL Library backup), and an older backup's schema is brought up to date
  automatically.
- **Delete All Data** — wipes the entire index back to empty. You'd then run a
  full scan to rebuild it.

Restore and Delete are in a **Danger Zone**: each overwrites or erases your
library and **cannot be undone**, so they make you type a confirmation phrase
first. Download a backup before using either. (Neither can run while a scan is
in progress.)

## NSFW toggle

A global **NSFW On/Off** switch in the top-right of the nav. When off, models
flagged NSFW are blurred in the grid and detail view. You can flag/unflag any
model from its card or detail header, and filter by NSFW status in the Library.
