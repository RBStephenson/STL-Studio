import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import {
  Rocket, LayoutGrid, Layers, FileBox, Box, Image as ImageIcon,
  Star, Wrench, Globe, AlertTriangle, Tags, Users, FolderSearch,
  Settings as SettingsIcon, Database, EyeOff, LifeBuoy, FolderOpen, Heart, type LucideIcon,
} from "lucide-react";

/** A keyboard key, styled like the hints elsewhere in the app. */
function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="bg-gray-800 px-1.5 py-0.5 rounded border border-gray-700 font-mono text-xs text-gray-300">
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
          STL Library catalogues the 3D-model files already on your drives. It never
          downloads or moves anything — it reads your folders, builds a searchable index,
          and lets you browse, tag, preview, and plan prints.
        </p>
        <ol>
          <li>Open <strong>Settings</strong> and add the folder path(s) where your models live.</li>
          <li>Click <strong>Scan Library</strong>. The first scan can take a few minutes for a large collection — models appear as they're found.</li>
          <li>Browse the <strong>Library</strong>, filter to what you want, and start tagging and queueing prints.</li>
        </ol>
        <p className="text-gray-500">
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
            <strong>Filters:</strong> creator, source site, tag, NSFW, has-image,
            needs-review, favorites, in-queue, and printed. Open the <strong>Filters</strong>{" "}
            panel for the full set, or use the quick chips in the header.
          </li>
          <li>
            <strong>Saved presets:</strong> dial in a set of filters, then save it as a
            named preset (stored in your browser) and re-apply it with one click.
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
        <ul>
          <li>
            <strong>Drag-to-group (Library):</strong> hover a card, grab the grip in its
            bottom-left corner, and drop it onto another card from the <em>same creator</em>.
            A prompt (pre-filled with the target's name) asks what to call the group.
          </li>
          <li>
            <strong>From a group card:</strong> open it and use <strong>Move to group</strong>{" "}
            (with name suggestions) or <strong>× Remove</strong> under any variant.
          </li>
          <li>
            <strong>From a model:</strong> the <strong>Set group</strong> button in the model
            header assigns or changes the group; leave it blank to ungroup.
          </li>
        </ul>
        <p className="text-gray-500">
          A group override applies immediately (no rescan needed) and takes precedence over
          the scanner's guess until you clear it.
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
          <li>Edit metadata, tags, source URL, and the NSFW flag.</li>
          <li>See and <strong>label each STL file</strong> (head, arm, base, etc.).</li>
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
          <li><strong>From URL</strong> — paste any image URL to use instead.</li>
          <li><strong>Clear</strong> — remove the thumbnail entirely.</li>
        </ul>
      </>
    ),
  },
  {
    id: "favorites-queue",
    title: "Favorites, queue & printed",
    icon: Star,
    body: (
      <>
        <p>Three independent ways to organize what you want to print — a model can be any combination.</p>
        <ul>
          <li><strong>★ Favorite</strong> — bookmark models you love, and filter to them with the header chip.</li>
          <li>
            <strong>🖨 Queue</strong> — add models to your print queue. The <strong>Queue</strong>{" "}
            page shows everything queued; <strong>drag the handle</strong> to set your own
            order, and favorites always float to the top.
          </li>
          <li>
            <strong>✓ Printed</strong> — mark a model printed. This records the date and
            removes it from the active queue. The Queue page keeps a <strong>Recently
            Printed</strong> history.
          </li>
        </ul>
        <p>Toggle favorite/queue from a card's hover icons or the model header; printed is set from the model header.</p>
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
          <strong>part label</strong> (head, torso, arms, base…). Pick one file per part
          group to assemble a complete build, then <strong>Copy list</strong> or{" "}
          <strong>Download zip</strong> of the selection.
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
          <strong>MyMiniFactory</strong> and it scrapes the page to fill in the title,
          description, creator, thumbnail, and tags. Bulk enrichment is available from the{" "}
          <strong>Creators</strong> page.
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
    title: "Bulk tag editor",
    icon: Tags,
    body: (
      <p>
        In the Library, hover a card and use the checkbox to select multiple models. A
        floating bar appears where you can <strong>add or remove tags</strong> or{" "}
        <strong>add to a collection</strong> across the whole selection at once.
      </p>
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
    id: "scanning",
    title: "Scanning & folder layout",
    icon: FolderSearch,
    body: (
      <>
        <p>The scanner expects roughly this shape, but it's flexible about depth:</p>
        <pre className="not-prose bg-gray-950 border border-gray-800 rounded-lg p-3 text-xs font-mono text-gray-400 overflow-x-auto">{`<scan root>/
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
    id: "backup",
    title: "Backup, restore & reset",
    icon: Database,
    body: (
      <>
        <p>
          At the bottom of <strong>Settings</strong>, under <strong>Data Management</strong>,
          you can manage the library database. This only ever touches the <em>index</em> —{" "}
          <strong>your STL files on disk are never modified.</strong>
        </p>
        <ul>
          <li><strong>Download Backup</strong> — saves a timestamped <code>.db</code> snapshot of your tags, favorites, and print queue. It's the only way to recover them if something goes wrong.</li>
          <li><strong>Restore from Backup…</strong> — replace your current library with a previously downloaded <code>.db</code>. This is also how you migrate to a new machine. The file is validated first.</li>
          <li><strong>Delete All Data</strong> — wipes the index back to empty; run a full scan to rebuild.</li>
        </ul>
        <p className="text-gray-500">
          Restore and Delete live in a <strong>Danger Zone</strong> and make you type a
          confirmation phrase, since they can't be undone. Neither runs while a scan is in progress.
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
        <p className="font-medium text-gray-200">I added models but they don't show up</p>
        <p>Run a <strong>Rescan</strong> on that creator from the Creators page. If the creator isn't listed yet (never scanned), run a full <strong>Scan Library</strong> first to discover it — after that, a per-creator Rescan works even for a creator that currently shows 0 models.</p>
        <p className="font-medium text-gray-200 mt-4">A whole creator is missing or shows one model</p>
        <p>Make sure the creator's folder is directly under one of your scan roots (see <a href="#scanning">folder layout</a>), then run a full scan.</p>
        <p className="font-medium text-gray-200 mt-4">Scale or type tags are wrong/missing</p>
        <p>Auto-tags come from folder and file names. Check the scale appears in a recognizable form (<code>1:6</code>, <code>1_6</code>, <code>75mm</code>), then rescan that creator. You can always add or remove tags yourself.</p>
        <p className="font-medium text-gray-200 mt-4">The scan seems stuck or slow</p>
        <p>The first full scan of a large library takes a while, and a slow external/USB drive or NAS is limited by that drive's speed. You can <strong>Cancel</strong> at any time — already-indexed models are kept.</p>
      </>
    ),
  },
  {
    id: "about",
    title: "About & support",
    icon: Heart,
    body: (
      <>
        <p className="font-medium text-gray-200">Like STL Library?</p>
        <p>
          STL Library started because I had a problem: way too many STL files and no good
          way to keep track of them all. What began as a personal tool turned into something
          I thought other makers, painters, gamers, and hobbyists might find useful too.
        </p>
        <p>
          If STL Library has helped you organize your collection, rediscover forgotten
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
          There's absolutely no obligation—STL Library is, and will remain, a passion
          project. But every bit of support is deeply appreciated and helps me continue
          building tools and content for the community.
        </p>
        <p>Thank you for being here, and happy printing!</p>
        <p className="text-gray-500">— Brent the Programmer</p>
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
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
            Help topics
          </p>
          <ul className="flex flex-col gap-0.5 border-l border-gray-800">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`block -ml-px border-l-2 pl-3 py-1 text-sm transition-colors ${
                    active === s.id
                      ? "border-indigo-500 text-indigo-300 font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-200 hover:border-gray-600"
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
          <p className="text-gray-500">
            How every part of STL Library works. Jump to a topic on the left, or scroll through.
          </p>
        </header>

        <div className="flex flex-col gap-12">
          {SECTIONS.map(({ id, title, icon: Icon, body }) => (
            <section key={id} id={id} className="scroll-mt-6">
              <h2 className="flex items-center gap-2 text-xl font-semibold text-white mb-3">
                <Icon size={18} className="text-indigo-400 shrink-0" />
                {title}
              </h2>
              <div className="help-prose text-sm text-gray-400 leading-relaxed flex flex-col gap-3">
                {body}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
