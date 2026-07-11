import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import {
  Rocket, LayoutGrid, Layers, FileBox, Box, Image as ImageIcon,
  Star, Wrench, Globe, AlertTriangle, Tags, Users, FolderSearch,
  Settings as SettingsIcon, Database, EyeOff, LifeBuoy, FolderOpen, Heart, Palette, Pipette, Tag, FolderSync, Inbox, type LucideIcon,
} from "lucide-react";

/** A keyboard key, styled like the hints elsewhere in the app. */
function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="bg-panel-secondary px-1.5 py-0.5 rounded border border-border font-mono text-xs text-text-primary-alt2">
      {children}
    </kbd>
  );
}

interface Section {
  id: string;
  title: string;
  icon: LucideIcon;
  body: ReactNode;
}

const SECTIONS: Section[] = [
  {
    id: "getting-started",
    title: "Getting started",
    icon: Rocket,
    body: (
      <>
        <p>
          STL Studio catalogues the 3D-model files already on your drives. It never
          downloads or moves anything — it reads your folders, builds a searchable index,
          and lets you browse, tag, preview, and plan prints.
        </p>
        <ol>
          <li>Open <strong>Settings</strong> and add the folder path(s) where your models live.</li>
          <li>Click <strong>Scan Library</strong>. The first scan can take a few minutes for a large collection — models appear as they're found.</li>
          <li>Browse the <strong>Library</strong>, filter to what you want, and start tagging and queueing prints.</li>
        </ol>
        <p className="text-text-secondary-alt">
          Everything runs locally. Your library never leaves your machine.
        </p>
      </>
    ),
  },
  {
    id: "library",
    title: "The Library",
    icon: LayoutGrid,
    body: (
      <>
        <p>
          The main grid. Every filter lives in the URL, so you can bookmark or share a
          filtered view.
        </p>
        <ul>
          <li><strong>Search</strong> by name, title, description, or character.</li>
          <li>
            <strong>Filters:</strong> creator (include or exclude), source site, tag,
            NSFW, has-image, needs-review, min star rating, favorites, in-queue, and
            printed. Open the <strong>Filters</strong> panel for the full set, or use
            the quick chips in the header.
          </li>
          <li>
            <strong>Negative tag filter:</strong> clicking a tag chip cycles through
            three states — <strong>include</strong> (show only models with that tag),{" "}
            <strong>exclude</strong> (a <code>≠ tag</code> chip; hides models with the
            tag), and <strong>off</strong>. One include and one exclude tag can be active
            at a time.
          </li>
          <li>
            <strong>Hide printed:</strong> the <strong>hide printed</strong> chip excludes
            already-printed models while keeping variant grouping on — the inverse of the{" "}
            <em>printed</em> chip. The two are mutually exclusive.
          </li>
          <li>
            <strong>Sort:</strong> the header dropdown orders the grid by Name, Date
            added (newest first), or Creator. Your choice is saved in presets and
            remembered as the default across browsers, and Prev/Next on a model walks
            the library in the same order.
          </li>
          <li>
            <strong>Recently added:</strong> the header chip filters to models added in
            the last few days, newest first; those cards also carry a <strong>New</strong>{" "}
            badge. Configure the window in Settings → Preferences.
          </li>
          <li>
            <strong>Saved presets:</strong> dial in a set of filters, then save it as a
            named preset and re-apply it with one click. Presets are stored server-side,
            so they follow you across browsers and devices.
          </li>
          <li>
            <strong>Pagination</strong> appears at both the top and bottom of the grid,
            with a jump-to-page box.
          </li>
        </ul>
        <p>
          Each card shows the thumbnail, name, and tags, plus favorite (★) and
          print-queue (🖨) icons on hover.
        </p>
        <p>
          <strong>Keyboard shortcuts:</strong> press <kbd>/</kbd> to jump to search,{" "}
          <kbd>A</kbd>/<kbd>D</kbd> and <kbd>W</kbd>/<kbd>S</kbd> (or the arrow keys) to
          move the focus ring between cards, <kbd>Enter</kbd> to open the focused model,
          and <kbd>Esc</kbd> to step back out. You can also group cards by keyboard:{" "}
          <kbd>Tab</kbd> to a card's grip, <kbd>Space</kbd> to pick it up, arrow keys to
          move it onto a target, then <kbd>Space</kbd>/<kbd>Enter</kbd> to group them.
          Press <kbd>?</kbd> any time for the full list.
        </p>
      </>
    ),
  },
  {
    id: "variant-grouping",
    title: "Variant grouping",
    icon: Layers,
    body: (
      <>
        <p>
          When several folders share the same character — for example a <em>Bust</em>, a{" "}
          <em>Full size</em>, and a <em>Pre-supported</em> version of one figure — the
          Library collapses them into a single <strong>group card</strong> with a
          "<em>N</em> variants" badge. Click it to open the group and see each variant
          individually. This keeps the grid tidy when a creator ships many cuts of one model.
        </p>
        <p>
          The scanner infers groups from folder names and is usually right, but you can
          fix any mis-grouping — corrections are saved and survive future rescans:
        </p>
        <p>
          If your folders are laid out as <code>{"{creator}/{character}/…"}</code>, turn on{" "}
          <strong>Group variants by character</strong> for that scan root (Settings →
          Library). The scanner then treats the first folder under the creator as the group
          — everything beneath it is one variant group, no name-guessing. Off by default;
          rescan to apply. Manual groupings still win.
        </p>
        <ul>
          <li>
            <strong>Drag-to-group (Library):</strong> hover a card, grab the grip in its
            bottom-left corner, and drop it onto another card from the <em>same creator</em>.
            Dropping onto an existing group adds the card straight to it; dropping onto a
            loose card opens a naming prompt. Select several cards first (checkboxes) and
            drag any one of them to group the <em>whole selection</em> at once. Drag a{" "}
            <em>group</em> card onto another to <strong>merge</strong> the two groups
            (after a confirm). The gesture also works by keyboard — <kbd>Tab</kbd> to a
            grip, <kbd>Space</kbd> to pick up, arrow keys to move, <kbd>Space</kbd>/
            <kbd>Enter</kbd> to drop.
          </li>
          <li>
            <strong>From a group card:</strong> open it to manage the whole group. Click the
            title to <strong>rename</strong> the group (applies to every variant). Use the
            per-card checkboxes (or <strong>Select all</strong>) to pick several variants, then{" "}
            <strong>Move to group</strong> them into another group, <strong>Set image</strong>{" "}
            (paste one image or product-page URL to give every selected variant the same
            thumbnail), or <strong>Ungroup</strong> them in one go. Each card also has its own{" "}
            <strong>Move to group</strong> (with name suggestions) and <strong>× Remove</strong>.
          </li>
          <li>
            <strong>Group thumbnail:</strong> the group's library card shows one variant's image.
            By default a variant you've <strong>favorited or queued</strong> is promoted to the
            front so its ★/🖨 chip shows on the group card; otherwise a variant that has a
            thumbnail represents the group. To pin a specific one, open the group and click the{" "}
            <strong>image button</strong> on that variant — <strong>Set as group thumbnail</strong>.
            The choice survives rescans.
          </li>
          <li>
            <strong>Reorder within a group:</strong> drag variant cards within the group view to
            set a custom display order. Use the <strong>Reset order</strong> button to go back to
            the default (favorited/queued first, then by thumbnail, then by name).
          </li>
          <li>
            <strong>From a model:</strong> the <strong>Merge into group</strong> button in the
            model header joins an existing group (autocompletes from that creator's groups);
            once grouped it becomes a <strong>Group: [name]</strong> chip with a{" "}
            <strong>×</strong> to remove the model from the group.
          </li>
        </ul>
        <p className="text-text-secondary-alt">
          Grouping is durable — it applies immediately (no rescan needed) and a future rescan
          never undoes it. Removing a model from a group keeps it out of auto-grouping until
          you merge it into a group again.
        </p>
      </>
    ),
  },
  {
    id: "model-detail",
    title: "Model detail",
    icon: FileBox,
    body: (
      <>
        <p>Click a card to open the model. From here you can:</p>
        <ul>
          <li>View and switch between all its preview images.</li>
          <li>Toggle to the <strong>3D viewer</strong> (if it has STL files).</li>
          <li>
            <strong>Edit tags inline</strong> — click the <strong>+</strong> button
            next to the tag list to add a tag (autocompletes from your library), or the{" "}
            <strong>×</strong> on any tag to remove it, without opening the full edit
            screen.
          </li>
          <li>Edit metadata, tags, source URL, and the NSFW flag (full form via <strong>Edit</strong>).</li>
          <li>See and <strong>label each STL file</strong> (head, arm, base, etc.).</li>
          <li>
            A part can have multiple <strong>sup variants</strong> — alternate
            supported/cut versions — and the part picker shows one button per sup
            variant (s1, s2, …). The file list and part picker stay in sync in both
            directions; changing a part's category applies to the base file and all
            its sups. Clicking the link icon to attach a sup opens a searchable
            picker — it lists each candidate by part name (or filename if it has
            none set), with the filename shown underneath, and typing filters by
            either.
          </li>
          <li>
            <strong>AI Organize</strong> suggests a category and cleaned-up name for
            every file, or links supported variants to their base part — pick a
            strategy when you click it. <strong>Parts-based</strong> and{" "}
            <strong>Unit-based</strong> both need an AI API assigned under Settings →
            AI & Integrations. <strong>Link supported parts</strong> doesn't — it's
            pure name matching (no AI call) that finds every currently-unlinked file
            named "Sup", "Supported", or "Hollowed" and matches it to a same-named
            plain file by filename. Either way, nothing is written until you review
            and apply the suggestions.
          </li>
          <li>
            <strong>Settings → Preferences → Horizontal parts layout</strong> swaps
            the two-column page for a full-width scrollable files table — handy for
            models with a lot of parts. Check one or more rows to reveal a{" "}
            <strong>Recategorize to…</strong> dropdown in the toolbar — offering the
            standard categories plus any custom category already used on this
            model — to bulk-move several files into a category at once.
          </li>
          <li>
            Files and categories sort numerically where a name has an embedded
            number, so "Body 2" comes before "Body 10" instead of after it.
          </li>
          <li><strong>Download all</strong> files as a zip, or open the <strong>Kit Builder</strong>.</li>
          <li>
            See the model's <strong>Location</strong> on disk — copy the path, or
            (standalone only) click <strong>Open folder</strong> to jump to it in your
            file manager.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "viewer",
    title: "3D viewer",
    icon: Box,
    body: (
      <>
        <p>On any model with STL files, switch to <strong>3D View</strong> to inspect the mesh:</p>
        <ul>
          <li>Drag to rotate freely in any direction, scroll to zoom, right-drag to pan.</li>
          <li>The camera auto-fits the model on load, so it's framed every time.</li>
          <li>If a model has several STLs, use the file buttons to switch which one you're viewing.</li>
          <li>A size warning appears for very large files — they can be slow to load in a browser.</li>
        </ul>
      </>
    ),
  },
  {
    id: "thumbnails",
    title: "Thumbnails (image picker)",
    icon: ImageIcon,
    body: (
      <>
        <p>
          If the auto-chosen thumbnail is wrong or missing, open a model and click{" "}
          <strong>Change image</strong> on the preview. The <strong>Set Thumbnail</strong>{" "}
          dialog offers:
        </p>
        <ul>
          <li><strong>From Folder</strong> — every image found in that model's own folder.</li>
          <li><strong>From URL</strong> — paste any image URL; the image is downloaded and stored locally, so it keeps working even when the site blocks hot-linking.</li>
          <li><strong>Clear</strong> — remove the thumbnail entirely.</li>
        </ul>
        <p className="text-text-secondary-alt">
          To clear an image fast without opening the dialog, use{" "}
          <strong>Clear image</strong> in a card's <strong>⋯ quick-assign</strong> menu, or the{" "}
          <strong>Clear image</strong> button next to <strong>Change image</strong> on the model page.
        </p>
      </>
    ),
  },
  {
    id: "favorites-queue",
    title: "Favorites, queue & printed",
    icon: Star,
    body: (
      <>
        <p>Two ways to organize what you want to print — a model can be favorited and have a print status at the same time.</p>
        <ul>
          <li><strong>★ Favorite</strong> — bookmark models you love, and filter to them with the header chip.</li>
          <li>
            <strong>🖨 Print status</strong> — each model moves through a single lifecycle:
            {" "}<strong>None → Queued → Printing → Printed</strong>. Click the printer icon to
            advance it. The <strong>Queue</strong> page shows everything queued;{" "}
            <strong>drag the handle</strong> to set your own order, and favorites always float
            to the top. Reaching <strong>Printed</strong> records the date, bumps the print
            count, and drops the model from the active queue — the Queue page keeps a{" "}
            <strong>Recently Printed</strong> history. If you marked something printed by
            mistake, click <strong>Undo printed</strong> in the model header to revert it
            (the print date is cleared). Filter by any status from the header chips.
          </li>
        </ul>
        <p>Set both from a card's hover icons or the model header.</p>
      </>
    ),
  },
  {
    id: "kit-builder",
    title: "Kit Builder",
    icon: Wrench,
    body: (
      <>
        <p>
          Launched from any model's detail page. It groups that model's STL files by their{" "}
          <strong>part label</strong> (head, torso, arms, base…). Click any file to toggle
          it into your selection — any number can be selected at once, nothing is
          exclusive — then <strong>Copy list</strong> or <strong>Download zip</strong> of
          the selection.
        </p>
        <p>
          A part with linked variants (Supported/Hollowed/other) renders as one box: the
          base part on top, each linked variant as a smaller labeled row below it. Click
          any row to toggle just that one file — the base and its variants can all be
          selected together.
        </p>
        <p>
          To make this useful, label your parts first: on the model detail page, each STL
          file has a small <strong>Label</strong> input with common suggestions.
        </p>
      </>
    ),
  },
  {
    id: "enrichment",
    title: "Metadata & web enrichment",
    icon: Globe,
    body: (
      <>
        <p>
          Open a model and click <strong>Edit</strong> to change the title, creator,
          description, notes, source URL, license, category, tags, and NSFW flag.
        </p>
        <p>
          The <strong>Source URL</strong> field has a <strong>Fetch</strong> button: paste
          a product page from <strong>Gumroad</strong>, <strong>Cults3D</strong>, or{" "}
          <strong>MyMiniFactory</strong> and it fills in the title, description, creator,
          thumbnail, tags, category, and license.
        </p>
        <p>
          To do this in bulk, use <strong>Enrich from web</strong> on the{" "}
          <strong>Creators</strong> page: paste a creator's storefront URL and it matches
          their listings to your local models, then fetches each matched product's full
          detail and applies the complete metadata in one pass — across every variant in a
          group, so you don't have to <em>Fetch</em> each model by hand. Expand any match
          (the chevron) to preview the description, tags, category, and license it would
          apply before you commit. MyMiniFactory and Cults3D use their APIs when configured
          under <strong>Settings → AI &amp; Integrations</strong>; Gumroad is scraped.
        </p>
      </>
    ),
  },
  {
    id: "triage",
    title: "Triage queue",
    icon: AlertTriangle,
    body: (
      <>
        <p>
          A keyboard-driven review screen for models the scanner flagged as uncertain
          (<code>needs_review</code>). Work through them quickly:
        </p>
        <ul className="not-prose flex flex-col gap-1.5">
          <li className="flex items-center gap-2"><Kbd>→ / Space</Kbd> dismiss (looks fine)</li>
          <li className="flex items-center gap-2"><Kbd>S</Kbd> skip</li>
          <li className="flex items-center gap-2"><Kbd>←</Kbd> go back</li>
        </ul>
        <p>The nav shows a live count of how many models still need review.</p>
      </>
    ),
  },
  {
    id: "collections",
    title: "Collections",
    icon: FolderOpen,
    body: (
      <>
        <p>
          Collections let you group models into named sets, independent of tags or creators —
          useful for projects, wishlists, or anything you want to track together.
        </p>
        <ul>
          <li>
            <strong>Create</strong> a collection from the Collections page (nav → Collections →
            New Collection).
          </li>
          <li>
            <strong>Rename</strong> — hover a collection card and click the pencil icon.
          </li>
          <li>
            <strong>Delete</strong> — hover a collection card and click the trash icon. Models
            are not deleted, only the grouping.
          </li>
          <li>
            <strong>Add a model</strong> — open a model's detail page, scroll to the
            Collections section, click <strong>Manage</strong>, and tick the collections you
            want. You can also create a new collection inline from that panel.
          </li>
          <li>
            <strong>Bulk add</strong> — select models in the Library using their hover
            checkboxes, then click <strong>Add to Collection</strong> in the floating bar.
          </li>
          <li>
            <strong>Remove a model</strong> — open the collection's detail view, hover the
            card, and click the <strong>×</strong> button.
          </li>
        </ul>
        <p>Collections are saved in your database and survive backup/restore.</p>
      </>
    ),
  },
  {
    id: "bulk-tags",
    title: "Bulk editor (tags & enrich)",
    icon: Tags,
    body: (
      <>
        <p>
          In the Library, hover a card and use the checkbox to select multiple models. A
          floating bar appears with actions across the whole selection at once:
        </p>
        <ul>
          <li><strong>Add or remove tags</strong> across every selected model.</li>
          <li><strong>Add to a collection</strong> in one step.</li>
          <li>
            <strong>Enrich</strong> — set <strong>creator</strong>,{" "}
            <strong>character</strong>, and/or <strong>title</strong> across the
            selection. Leave a field blank to leave it untouched. The fast way to fill
            in metadata for loose or badly-named <a href="#import">imports</a> so they
            become eligible for <a href="#reorganize">Reorganize</a>.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "import",
    title: "Import folder",
    icon: Inbox,
    body: (
      <>
        <p>
          <strong>Import</strong> (nav bar, at <code>/import</code>) brings an arbitrary
          folder of loose downloads or an unzipped pack into the catalog{" "}
          <strong>without</strong> adding it as a permanent scan root, then files it into a
          managed library on disk — the full <em>import → enrich → organize</em> pipeline
          on one screen.
        </p>
        <p>
          <strong>First, set up a library.</strong> A <em>library</em> is a folder you've
          named and marked as an <strong>Import destination</strong> in{" "}
          <a href="#settings">Settings</a> (a folder card → <strong>Library</strong> name +{" "}
          <strong>Import destination</strong> checkbox). Only those appear as a move target.
        </p>
        <ul>
          <li>
            <strong>Pick a source folder</strong> at <code>/import</code> →{" "}
            <strong>Preview packs</strong>. You land on the <strong>Import Preview</strong>{" "}
            screen with <strong>one card per pack</strong> (each immediate subfolder).
          </li>
          <li>
            <strong>Choose the destination Library</strong> once. It's saved as a{" "}
            <strong>source → library mapping</strong> — every pack inherits it and it
            pre-fills next time.
          </li>
          <li>
            <strong>Enrich + Import each pack</strong> — expand a card, set{" "}
            <strong>Creator / Character / Title / Tags</strong>, then <strong>Import</strong>{" "}
            (ingests that pack as inbox models and applies the metadata).
          </li>
          <li>
            <strong>Move them in</strong> — the{" "}
            <strong>"Move N imported packs → library"</strong> bar files the packs into the
            library on disk (drift-checked, with undo). The inbox flag clears as they land;
            blocked packs are reported as skipped.
          </li>
          <li>
            <strong>Quick import (whole folder)</strong> — the original one-shot index of
            the entire source in one pass, when you don't need per-pack review. Imported
            models are flagged <strong>inbox</strong> (the <code>?is_inbox=1</code> Library
            filter shows them).
          </li>
        </ul>
        <p className="text-text-secondary-alt">
          Like <a href="#reorganize">Reorganize</a>, the move step is{" "}
          <strong>standalone-only</strong> (Docker mounts are read-only) and needs write
          mode; importing and enriching work everywhere.
        </p>
      </>
    ),
  },
  {
    id: "creators",
    title: "Creators & per-creator rescan",
    icon: Users,
    body: (
      <>
        <p>The <strong>Creators</strong> page lists every creator with their model count. From here you can:</p>
        <ul>
          <li>Click a creator to browse just their models.</li>
          <li>
            <strong>Rescan</strong> a single creator — a targeted scan of just that
            creator's folder. Since you usually add models one creator at a time, this is
            much faster than a full library scan.
          </li>
          <li><strong>Enrich from web</strong> — match a creator's online storefront listings against your local models and bulk-apply metadata.</li>
        </ul>
      </>
    ),
  },
  {
    id: "paint-shelf",
    title: "Paint Shelf (painting guides)",
    icon: Palette,
    body: (
      <>
        <p>
          The <strong>Paint Shelf</strong> is always in the nav — it's standalone
          paint inventory. Turning on <strong>Settings → Painting Guides</strong>{" "}
          additionally adds the <strong>Guides</strong> entry for authoring and
          reading step-by-step painting guides.
        </p>
        <p>
          The <strong>Paint Shelf</strong> is a table of every paint you own (or
          want). Search by name or code, filter by brand, line, finish, or owned
          state, and see a <strong>color chip</strong> for any paint with a swatch
          color set. Add or edit paints inline with the <strong>Add paint</strong>{" "}
          form.
        </p>
        <p>
          A paint line can declare a <strong>code pattern</strong> (a regex like{" "}
          <code>{"^MPA-\\d{3}$"}</code>); codes are then validated on entry, so
          typos like <code>MPA-12</code> are caught with a clear message instead of
          polluting the shelf.
        </p>
        <p className="font-medium text-text-primary-alt">PaintRack CSV import &amp; export</p>
        <p>
          The import/export uses the CSV format from{" "}
          <a href="https://www.courageousoctopus.com/" target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:text-indigo-300 underline">PaintRack</a>{" "}
          by Courageous Octopus — a great paint-inventory app. STL Studio isn't
          affiliated with it; we just interoperate with its export.
        </p>
        <p>If you track paints in <strong>PaintRack</strong>, import its CSV export directly:</p>
        <ul>
          <li>
            <strong>Import CSV</strong> shows a <strong>diff preview</strong> first —
            what would be added, changed, or removed — and writes nothing until you
            confirm. Removals are off by default behind a separate checkbox, and only
            ever touch paints that came from a previous import; paints you added by
            hand are never deleted.
          </li>
          <li>
            Codes that don't match a line's code pattern are listed as{" "}
            <strong>warnings</strong> in the preview — informational only, the rows
            still import.
          </li>
          <li>
            <strong>Export CSV</strong> downloads your shelf in the same format, and an
            export re-imports as an empty diff (a lossless round-trip).
          </li>
        </ul>
        <p>
          The CSV has an optional seventh <strong>Color</strong> column, so an import
          can pre-populate swatch colors and every export includes the ones you've set.
          Hex (<code>#2A2A2A</code>), <code>rgb(…)</code>, and <code>hsv(…)</code> are
          all accepted and normalized to hex on import — because the latter two contain
          commas, those cells must be <strong>quoted</strong>. Files without the column
          (like real PaintRack exports) import exactly as before, and an empty color
          cell never clears a swatch you've already set.
        </p>
        <p className="font-medium text-text-primary-alt">Painting guides</p>
        <p>
          The <strong>Guides</strong> page lists your guides; open one to read it
          in-app — a tabbed, step-by-step recipe with value maps, numbered steps,
          <strong> paint swatches</strong> drawn from your shelf, and a shared
          Thinning Reference. <strong>Print</strong> expands every tab into one
          print-styled document with dark backgrounds and paint chip colors preserved, and{" "}
          <strong>Export PDF</strong> saves that same document as a downloadable PDF
          (the standalone build needs a one-time{" "}
          <code>playwright install chromium</code> the first time you export).
          A model with a guide shows a <strong>Guide</strong>{" "}
          badge on its Library card and a <strong>Painting guide</strong> button on
          its detail page, and the guide links back to its model.
        </p>
        <p>
          <strong>Mix swatches</strong> — a step can reference a blend like{" "}
          <em>Paint A + Paint B (3:1)</em>. These import from guide HTML, render as
          a single blended-dot chip in the reader, and round-trip cleanly on export.
        </p>
        <p>
          <strong>Import guide</strong> (top of the Guides page) uploads a guide HTML
          file — click to browse or <strong>drag and drop</strong> an{" "}
          <code>.html</code> file onto the dropzone. It lands as a{" "}
          <strong>draft</strong>. If all paints resolve against your shelf the guide
          imports immediately; otherwise a <strong>Paint resolution</strong> step
          appears — for each unresolved paint you can <strong>Map</strong> it to an
          existing shelf paint, <strong>Force-add</strong> it to your shelf
          (pre-filled with the swatch color from the guide), or <strong>Skip</strong>{" "}
          it (the swatch is dropped). Once everything is resolved or skipped the guide
          imports. From an open guide you can <strong>Publish / Unpublish</strong> it
          or <strong>Delete</strong> it.
        </p>
        <p>
          <strong>New guide</strong> (top of the Guides page) opens a short
          <strong> wizard</strong> — title, scale, category, and an optional link to
          a model in your library — then drops you into the editor. <strong>Edit</strong>{" "}
          (on an open guide) changes its title, subtitle, scale, franchise, technique
          tags, creator credit and other details. <strong>Edit content</strong> opens
          a structured editor for the guide's tabs, phases, steps and paint swatches —
          add, remove and <strong>drag to reorder</strong> at every level, pick swatch
          paints from your shelf, and watch a <strong>live preview</strong> update as
          you go. Saving content replaces the guide's tab tree; saving metadata leaves
          the content untouched.
        </p>
        <p>
          A <strong>validation panel</strong> flags problems as you edit: blocking
          issues (a swatch paint you don't own, or a code that fails its line's
          pattern) must be fixed before you can <strong>publish</strong>, while
          warnings (an empty tab, a step with no swatches) are advisory.
        </p>
        <p>
          <strong>Theming</strong> — the editor's <strong>Theme</strong> section has
          colour pickers for the guide's background, surfaces, text and accent (plus a
          hero gradient) with a live preview. Leave a field blank to inherit the{" "}
          <strong>default guide theme</strong> from{" "}
          <strong>Settings → Painting Guides</strong>, which every new guide starts
          from. Themes apply in the reader and the exported PDF.
        </p>
        <p>
          <strong>Exporting</strong> — the <strong>Export PDF</strong> menu adds
          per-export <strong>reward stamping</strong>: a Patreon-exclusive footer (on
          by default), an optional tier label, and a watermark (off by default). If a
          guide belongs to a <strong>series</strong>, <strong>Export series bundle</strong>{" "}
          renders every published guide in that series into one PDF with an optional
          cover page.
        </p>
      </>
    ),
  },
  {
    id: "color-match",
    title: "Color-match studio",
    icon: Pipette,
    body: (
      <>
        <p>
          The <strong>Color-match studio</strong> (the <strong>Color match</strong>{" "}
          button on the Paint Shelf) suggests paints from your shelf that match a
          reference photo — drop in a render or a painted mini and it samples the
          colors for you.
        </p>
        <p>
          It leads with <strong>value</strong>, then hue. For each sampled color you
          get a <strong>Value ladder</strong> — a <strong>shadow → mid → highlight</strong>{" "}
          ramp in the same hue family, anchored on the sampled mid-tone (Dark Camo
          Green → Green → Bright Yellow-Green), so the steps read as a cohesive
          recipe. Then a <strong>Hue match</strong> (opaque paints ranked by ΔE2000),
          and a labelled <strong>Glaze / wash</strong> list for transparents. Every
          suggestion carries a confidence band (<em>very close</em>, <em>confirm</em>,
          <em> family</em>, <em>loose</em>) — these are starting points to{" "}
          <strong>confirm by eye</strong> under your bench light, never auto-applied.
        </p>
        <p>
          <strong>Eyedropper</strong> — click anywhere on the preview to match that
          exact spot. Sample the skin, then the hair, then the leather, and each gets
          its own suggestions. The <strong>Palette overview</strong> below it is an
          automatic read of the whole image (the background is excluded so the subject
          leads, not the backdrop).
        </p>
        <p>
          <strong>Value mode</strong> (on by default) greys every swatch so you can
          read values; turn it off to compare hues in full color. Large photos are
          automatically downscaled in your browser before upload, so even a phone shot
          uploads instantly.
        </p>
      </>
    ),
  },
  {
    id: "scanning",
    title: "Scanning & folder layout",
    icon: FolderSearch,
    body: (
      <>
        <p>The scanner expects roughly this shape, but it's flexible about depth:</p>
        <pre className="not-prose bg-panel-inset border border-border-subtle rounded-lg p-3 text-xs font-mono text-text-secondary overflow-x-auto">{`<scan root>/
  <Creator>/              ← top-level folder = a creator
    <Character>/          ← optional grouping
      Renders/            ← preview images
      <Variant>/          ← a MODEL (head.stl, body.stl…)
      <Another Variant>/  ← a separate MODEL`}</pre>
        <ul>
          <li>By default the top-level folder under a scan root is a <strong>creator</strong>, never a model. If your creators live deeper (e.g. under a genre folder), set a <strong>custom layout</strong> on that scan root in Settings — for example <code>{"{tag}/{creator}"}</code> tags every model with the folder above the creator.</li>
          <li>A <strong>model</strong> is a folder whose subtree contains 3D files (<code>.stl</code> / <code>.3mf</code> / <code>.obj</code>). Render-only folders are skipped.</li>
          <li><strong>Auto-tags</strong> are detected from folder/file names — scale (<code>1:6</code>, <code>75mm</code>), type (bust, statue, terrain), and modifiers (pre-supported, NSFW). They're kept separate from tags you add, and refresh on every scan.</li>
          <li>A <strong>full scan</strong> is incremental — unchanged folders skip the expensive file-indexing step, but metadata and tags still refresh.</li>
        </ul>
      </>
    ),
  },
  {
    id: "scan-rules",
    title: "Scan rules",
    icon: FolderSearch,
    body: (
      <>
        <p>
          Under <strong>Settings → Scan Rules</strong> you can customise how the scanner
          interprets your folders. Each list <em>adds</em> to the built-in behaviour — you
          can extend the defaults but never break them. All three apply on the next scan.
        </p>
        <ul>
          <li>
            <strong>Ignore patterns</strong> — folders matching a pattern (and everything
            inside) are skipped entirely. Matching is case-insensitive against a folder's
            name (<code>WIP</code>) or its full path (<code>{"*/_archive/*"}</code>).
            Adding a pattern also removes any already-indexed models it now covers on the
            next scan.
          </li>
          <li>
            <strong>Tag rules</strong> — a keyword→tag pair adds an auto-tag to any model
            whose name contains the whole keyword, e.g. <code>Aztec</code> →{" "}
            <code>civ</code>. These supplement the built-in tag detection and don't affect
            how variants group.
          </li>
          <li>
            <strong>Parts folder names</strong> — exact folder names (e.g.{" "}
            <code>Sprues</code>, <code>Magnets</code>) treated as parts/structure: never
            indexed as their own model and never used to group variants, alongside the
            built-ins (Parts, Base, Supports…).
          </li>
        </ul>
        <p className="text-text-secondary-alt">
          A safety cap prevents an over-broad ignore pattern from wiping your library: if a
          single scan would remove more than half your models, the cleanup is skipped and
          logged instead.
        </p>
      </>
    ),
  },
  {
    id: "settings",
    title: "Settings",
    icon: SettingsIcon,
    body: (
      <p>
        At <strong>Settings</strong> you manage your <strong>scan roots</strong> — the
        top-level folder paths the app reads from. Add or remove paths and see when each
        was last scanned. Use <strong>Browse…</strong> to pick a folder, or type the full
        path. Each scan root also has a <strong>Layout</strong> field describing how its
        folders are arranged (see <a href="#scanning">folder layout</a>) — leave it as
        <code>{"{creator}"}</code> unless your creators sit below a genre or wrapper
        folder. This is also where standalone users point the app at their drives for the
        first time, and it's home to <strong>Data Management</strong> (below).
      </p>
    ),
  },
  {
    id: "reorganize",
    title: "Reorganize library",
    icon: FolderSync,
    body: (
      <>
        <p>
          <strong>Settings → Library Tools → Reorganize Library</strong> (or navigate
          to <code>/reorganize</code>) tidies your files on disk to match a folder
          template — by default <code>{"{creator}/{character}/{title}"}</code>.
        </p>
        <p>
          Templates can also include <code>{"{scale}"}</code>, using scanner-detected
          scale tags like <code>1:6</code> or <code>75mm</code>.
        </p>
        <p className="font-medium text-text-primary-alt">How it works</p>
        <ul>
          <li>
            <strong>Preview first.</strong> The page shows a per-model plan: which
            files would move, where, and what kind of operation it is (move, rename,
            case rename, or already in place). No files are touched yet.
          </li>
          <li>
            <strong>Resolve flagged rows.</strong> Rows marked{" "}
            <em>unclassifiable</em> (missing creator, character, or title),{" "}
            <em>collision</em>, <em>over-length</em>, or <em>reserved name</em> are
            ineligible to apply. Click the row to expand it and fill in the{" "}
            <strong>creator / character / title / suffix</strong> override fields.
            The preview re-runs automatically with your values, and a resolved row
            becomes eligible.
          </li>
          <li>
            <strong>Select and apply.</strong> Tick the checkboxes on eligible rows,
            then click <strong>Apply</strong>. The app verifies each file's size and
            modification time against the preview fingerprint first — if anything
            drifted on disk, the whole batch aborts safely. All moves complete before
            the catalog is updated.
          </li>
          <li>
            <strong>Undo.</strong> After a successful apply, an{" "}
            <strong>Undo last apply</strong> button appears. It reads the apply log
            and reverses every move. Running it twice is safe — already-reversed files
            are skipped, not double-moved.
          </li>
        </ul>
        <p>
          The filter tabs (<em>Moves</em>, <em>Collisions</em>,{" "}
          <em>Unclassifiable</em>, <em>Blocked</em>, <em>Already In Place</em>) let
          you focus on what needs attention.
        </p>
        <p className="text-text-secondary-alt">
          Apply moves real files on disk.{" "}
          <strong>Standalone-only</strong> — it is disabled in the Docker build where
          library mounts are read-only. Back up your library (and your database) before
          applying a large reorganize.
        </p>
      </>
    ),
  },
  {
    id: "backup",
    title: "Backup, restore, repair & reset",
    icon: Database,
    body: (
      <>
        <p>
          At the bottom of <strong>Settings</strong>, under <strong>Data Management</strong>,
          you can manage the library database. This only ever touches the <em>index</em> —{" "}
          <strong>your STL files on disk are never modified.</strong>
        </p>
        <ul>
          <li><strong>Check Health</strong> runs SQLite's integrity check without changing the database.</li>
          <li><strong>Repair Database</strong> snapshots the database, runs a conservative <code>REINDEX</code>, and verifies integrity again. It can fix index-only corruption; deeper corruption still needs a clean backup or manual recovery.</li>
          <li><strong>Download Backup</strong> — saves a timestamped <code>.db</code> snapshot of your tags, favorites, and print queue. It's the only way to recover them if something goes wrong.</li>
          <li><strong>Restore from Backup…</strong> — replace your current library with a previously downloaded <code>.db</code>. This is also how you migrate to a new machine. The file is validated first.</li>
          <li><strong>Delete All Data</strong> — wipes the index back to empty; run a full scan to rebuild.</li>
        </ul>
        <p className="text-text-secondary-alt">
          Restore and Delete live in a <strong>Danger Zone</strong> and make you type a
          confirmation phrase, since they can't be undone. Neither runs while a scan is in progress.
          Repair also requires the confirmation phrase because it modifies SQLite indexes.
        </p>
      </>
    ),
  },
  {
    id: "nsfw",
    title: "NSFW toggle",
    icon: EyeOff,
    body: (
      <p>
        A global <strong>NSFW On/Off</strong> switch sits in the top-right of the nav. When
        off, models flagged NSFW are blurred in the grid and detail view. You can flag or
        unflag any model from its card or detail header, and filter by NSFW status in the Library.
      </p>
    ),
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting",
    icon: LifeBuoy,
    body: (
      <>
        <p className="font-medium text-text-primary-alt">I added models but they don't show up</p>
        <p>Run a <strong>Rescan</strong> on that creator from the Creators page. If the creator isn't listed yet (never scanned), run a full <strong>Scan Library</strong> first to discover it — after that, a per-creator Rescan works even for a creator that currently shows 0 models.</p>
        <p className="font-medium text-text-primary-alt mt-4">A whole creator is missing or shows one model</p>
        <p>Make sure the creator's folder is directly under one of your scan roots (see <a href="#scanning">folder layout</a>), then run a full scan.</p>
        <p className="font-medium text-text-primary-alt mt-4">Scale or type tags are wrong/missing</p>
        <p>Auto-tags come from folder and file names. Check the scale appears in a recognizable form (<code>1:6</code>, <code>1_6</code>, <code>75mm</code>), then rescan that creator. You can always add or remove tags yourself.</p>
        <p className="font-medium text-text-primary-alt mt-4">The scan seems stuck or slow</p>
        <p>The first full scan of a large library takes a while, and a slow external/USB drive or NAS is limited by that drive's speed. You can <strong>Cancel</strong> at any time — already-indexed models are kept.</p>
      </>
    ),
  },
  {
    id: "tags",
    title: "Tag Management",
    icon: Tag,
    body: (
      <>
        <p>
          The <strong>Tags</strong> page (nav bar) lists every tag in the library with a model
          count. Three actions are available per tag:
        </p>
        <ul>
          <li>
            <strong>Rename</strong> — changes the tag name on every model that carries it.
            Renaming to a name a model already has deduplicates silently.
          </li>
          <li>
            <strong>Merge</strong> — pick a target tag from the dropdown; all models get
            the target tag and the source tag is removed. Use this to consolidate typos
            or near-duplicates (<em>figure</em> + <em>figures</em> → <em>figure</em>).
          </li>
          <li>
            <strong>Delete</strong> — removes the tag from every model. A confirmation
            dialog shows how many models are affected.
          </li>
        </ul>
        <p>
          Changes are applied immediately and reflected in the Library without a rescan.
        </p>
      </>
    ),
  },
  {
    id: "about",
    title: "About & support",
    icon: Heart,
    body: (
      <>
        <p className="font-medium text-text-primary-alt">Like STL Studio?</p>
        <p>
          STL Studio started because I had a problem: way too many STL files and no good
          way to keep track of them all. What began as a personal tool turned into something
          I thought other makers, painters, gamers, and hobbyists might find useful too.
        </p>
        <p>
          If STL Studio has helped you organize your collection, rediscover forgotten
          models, or simply spend less time hunting through folders, please consider
          supporting the project through{" "}
          <a href="https://www.patreon.com/BrentStephenson" target="_blank" rel="noreferrer">Patreon</a> or{" "}
          <a href="https://www.buymeacoffee.com/brent_the_programmer" target="_blank" rel="noreferrer">Buy Me a Coffee</a>.
        </p>
        <p>
          Your support helps fund continued development, but it also helps keep resin in the
          printer, paint on the hobby desk, and supports my family as I balance software
          development, creativity, and caregiving.
        </p>
        <p>
          There's absolutely no obligation—STL Studio is, and will remain, a passion
          project. But every bit of support is deeply appreciated and helps me continue
          building tools and content for the community.
        </p>
        <p>Thank you for being here, and happy printing!</p>
        <p className="text-text-secondary-alt">— Brent the Programmer</p>
      </>
    ),
  },
];

export default function Help() {
  const { hash } = useLocation();
  const [active, setActive] = useState<string>(SECTIONS[0].id);
  const contentRef = useRef<HTMLDivElement>(null);

  // Scroll to the hash target on load / when it changes.
  useEffect(() => {
    const id = hash.replace("#", "");
    if (!id) return;
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash]);

  // Scrollspy: highlight the TOC entry for the section nearest the top.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-80px 0px -70% 0px", threshold: 0 }
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 flex gap-8">
      {/* Table of contents */}
      <aside className="hidden lg:block w-56 shrink-0">
        <nav className="sticky top-6">
          <p className="text-xs font-semibold text-text-secondary-alt uppercase tracking-wider mb-3">
            Help topics
          </p>
          <ul className="flex flex-col gap-0.5 border-l border-border-subtle">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`block -ml-px border-l-2 pl-3 py-1 text-sm transition-colors ${
                    active === s.id
                      ? "border-accent-start text-indigo-300 font-medium"
                      : "border-transparent text-text-secondary-alt hover:text-text-primary-alt hover:border-border-divider"
                  }`}
                >
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      {/* Content */}
      <div ref={contentRef} className="flex-1 min-w-0 max-w-3xl">
        <header className="mb-10">
          <h1 className="text-3xl font-bold text-white mb-2">Help &amp; Guide</h1>
          <p className="text-text-secondary-alt">
            How every part of STL Studio works. Jump to a topic on the left, or scroll through.
          </p>
        </header>

        <div className="flex flex-col gap-12">
          {SECTIONS.map(({ id, title, icon: Icon, body }) => (
            <section key={id} id={id} className="scroll-mt-6">
              <h2 className="flex items-center gap-2 text-xl font-semibold text-white mb-3">
                <Icon size={18} className="text-indigo-400 shrink-0" />
                {title}
              </h2>
              <div className="help-prose text-sm text-text-secondary leading-relaxed flex flex-col gap-3">
                {body}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
