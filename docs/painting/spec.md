# Figure Painting Guide — Web App

## Product Requirements & Technical Design Document

**Author:** Brent **Status:** v1.0 — build-ready (review-complete) **Date:** 2026-06-07 **Codename:** *Valuesmith* (working title — "values first, color second") **Delivery decision:** Built as a **new module inside the existing** [**STL-Inventory**](https://github.com/RBStephenson/STL-Inventory) **app** — not a standalone product. It inherits that app's stack, Docker setup, packaging, backup/restore, settings, and CI, and gains a first-class link between a **painted figure's guide** and the **STL model it was printed from**. See Section 3.

  

## 0\. How to read this doc

This is a full PRD + technical design intended to be handed to Code (or any engineer) to start building. It is organized so you can read top-to-bottom for the product story, or jump to Section 6 (Data Model) and Section 7 (API) when you're ready to scaffold.

  

Two things to keep front-of-mind throughout:

  

1.  **We already have a working "v0."** The current system is a Claude skill (figure-painting) that emits self-contained HTML guides styled by a shared guide.css / guide.js / skills-reference.js asset bundle, organized into by-category/ folders with an index.html gallery. This web app is a migration *and* an upgrade of that system — not a greenfield invention. The visual language, the value-first philosophy, the swatch/step-card structure, and the paint-code conventions are all **fixed requirements**, not open questions.
2.  **The hardest correctness problems are painting-domain problems, not web problems.** Color accuracy, paint-code validation, inventory truth, and value-first recipes are where this product lives or dies. The architecture below treats the paint inventory and the recipe schema as the load-bearing core, with the web stack wrapped around them.
3.  **We are not building infrastructure — we're extending an app that already has it.** STL-Inventory is Brent's local hobby app (FastAPI + SQLAlchemy + SQLite + React 18 + Vite + TypeScript + Tailwind + nginx + Docker, with standalone single-binary packaging, backup/restore, a settings page, in-app help, and a GitHub Actions release pipeline). This module plugs into all of that, so the entire "foundations" milestone collapses into "add tables, routes, and screens to a running app." Where this doc earlier proposed Postgres/Celery/Redis, it now **adopts STL-Inventory's choices** (SQLite, in-process jobs) to stay consistent with the host app.

  

## 1\. Vision & goals

### 1.1 One-line vision

A local web app where Brent authors value-first painting guides (AI-drafted, human-edited) and exports them as polished, downloadable PDFs — Patreon rewards for hobbyist caregivers — with every paint recipe grounded in a real, owned paint inventory and matched to a reference image. (A public browsable gallery is designed-for but deferred.)

### 1.2 Goals

  - **Replace the static-HTML-file workflow** with a real application: structured data in, consistent rendered guides out, no hand-managed index.html.
  - **Hybrid authoring:** an LLM produces a first-draft recipe; Brent edits it in a UI before publishing. The AI never publishes directly.
  - **Grounded recipes:** every swatch references a paint that exists in the inventory, with a validated code and an approximate hex chip. No invented paints.
  - **Color matching:** match a figure's reference image (uploaded *or* AI-generated *or* user-supplied web image *or* the STL model's own folder thumbnail) against the owned inventory to suggest candidate paints.
  - **Model↔guide link:** a guide can reference the STL-Inventory model it's printed from; a model can show "has a painting guide." This is the payoff of building inside STL-Inventory.
  - **Library organization** with category grouping and cross-guide "series" linking preserved (powers the admin library and PDF bundling).
  - **Downloadable PDFs** of published guides (rendered from print.css) for use as **Patreon subscriber rewards**.
  - **Ships inside STL-Inventory** — same local Docker / standalone-binary deployment, same backup file, no new infrastructure.
  - **Reusable by anyone, leaks nothing.** Ships in public builds as an opt-in, **bring-your-own-API-key** feature; none of Brent's keys, paint data, or Patreon branding are committed or bundled.
  - **Inclusive, caregiver-friendly tone** throughout (channel principle: self-care is valid; avoid "easy"/"no skill" language).

### 1.3 Non-goals (v1)

  - **Public-facing website / gallery.** Deferred. Since published guides are distributed as **downloadable PDFs** (Patreon rewards), a public web surface isn't needed for v1. The app is the **admin authoring tool**; the PDF is the published artifact. The data model still carries category/series grouping (it's useful for organizing the library and bundling PDFs), and the public gallery can be layered on later with no schema changes — see Section 3 and Section 16.
  - **Multi-tenant / multi-user accounts.** The module *is* reusable by other makers (it ships in public builds, opt-in, bring-your-own-key — Section 4.7), but each install is **single-user**, like STL-Inventory itself. We are not building accounts, roles, or shared servers.
  - Mobile-native apps. Responsive web only.
  - Cloud hosting, custom domains, CDNs, public deployment. v1 runs locally in Docker; remote hosting is a later concern.
  - Patreon API integration / gated access control. PDFs are *generated and downloaded* by Brent, then uploaded to Patreon manually. (Auto-posting to Patreon is out of scope for v1.)
  - E-commerce, paint purchasing, or affiliate integration.
  - Real-time collaboration / live co-editing.
  - Replacing the Claude skill *entirely* — see Section 12 (the skill can remain a generation backend option).

### 1.4 Success criteria

|  |  |
| :-: | :-: |
| \*\*\\\#\*\* | \*\*Criterion\*\* |
| S1 | Brent can produce a publishable guide end-to-end in the app in less time than the current skill+edit loop. |
| S2 | A published guide is visually indistinguishable from the current hand-built HTML guides (same guide.css design language). |
| S3 | Zero published swatches reference a paint not in inventory; 100% of Pro Acryl codes pass code-convention validation. |
| S4 | Publishing a guide produces a Patreon-ready PDF (single or series-bundle) rendered from print.css, with category/series grouping driven by data — no manual index editing. |
| S5 | Color-match suggestions return the correct owned paint family for a sampled region in the majority of test cases. |

  

## 2\. Personas

**Brent (Admin / Author).** Staff engineer, experienced painter. Wants speed and control. Will not tolerate the app "helpfully" inventing paints or flattening values. Needs an override on every AI suggestion. Cares about consistency of layout above creativity.

  

**The Viewer (Public / Caregiver-hobbyist).** Visits from the brent\_the\_programmer channel. May be a beginner or returning hobbyist painting as self-care. Reads guides at a workbench, often on a tablet, in controlled/dim lighting (hence the dark theme). Needs clarity, encouragement, printability, and zero jargon-gatekeeping.

  

## 3\. Scope: a module inside STL-Inventory

The painting app is **a new section of STL-Inventory**, not a separate product. STL-Inventory already catalogs the STL/3MF models Brent prints; this module adds the *next step in the hobby workflow* — painting the thing you printed — and links the two.

  

┌──────────────────────────────────────────────────────────────────┐

  

│                  STL-INVENTORY (existing app)                     │

  

│      FastAPI + SQLAlchemy + SQLite + React/Vite/Tailwind +        │

  

│         nginx + Docker + standalone binary + backup/CI           │

  

├───────────────────────────────┬──────────────────────────────────┤

  

│   EXISTING: Model Library      │   NEW: Painting Guides module     │

  

│   • model catalog + scan       │   • guide authoring (AI + edit)   │

  

│   • tags / collections         │   • Paint Shelf (paint inventory) │

  

│   • favorites / print queue     │   • color-match studio            │

  

│   • Kit Builder / part labels  │   • reference images              │

  

│   • model detail page          │   • publish → PDF (Patreon)       │

  

│              └───────────  model ↔ guide link  ──────────┘        │

  

└──────────────────────────────────────────────────────────────────┘

  

        Shared: one SQLite DB · one backup file · one Settings page

  

        · one Help system · one nav · one deploy (Docker / binary)

### 3.1 What we reuse (so we don't rebuild it)

|  |  |
| :-: | :-: |
| \*\*STL-Inventory capability\*\* | \*\*How the painting module uses it\*\* |
| Docker Compose + standalone binary packaging | Same deploy; no new infra. The module just adds backend routes + React screens. |
| SQLite + SQLAlchemy + backup/restore (.db snapshot) | Painting tables live in the \*\*same DB\*\*, so they're in every backup automatically. |
| Settings page | Add painting settings (Claude API key, PaintRack CSV path, PDF defaults) here. |
| In-app Help + contextual "?" deep-links | Add painting-guide help pages alongside the existing docs. |
| React/Vite/Tailwind shell, nav, card-grid, pagination, URL-driven filter state, localStorage filter presets | The guide \*\*Library\*\* and \*\*Paint Shelf\*\* reuse these patterns instead of inventing new ones. |
| Collections, tags, NSFW flag | Guides can reuse the tag/collection machinery for cross-cutting grouping. |
| GitHub Actions test + release pipeline | Painting backend tests join the existing pytest suite; releases ship the module with the app. |

### 3.2 The model↔guide link (the reason to do this)

  - A **guide** optionally references a **model** in the library (guide.model\_id). From a model's detail page: **"Create painting guide"** / **"View guide."** From a guide: a link back to the source model and its print files.
  - The model's **folder images** (already used as STL-Inventory thumbnails) become a **zero-effort top entry in the reference-image fallback chain** (Section 4.4) — the render you printed from is often the best color reference you have.
  - STL-Inventory's **part labels** (head, right arm, base, weapon…) map naturally onto a guide's **per-section recipes**, so a guide's tabs can be seeded from the model's labeled parts.

### 3.3 Naming: avoid the "inventory" collision

STL-Inventory's "Library/inventory" already means *the model catalog*. To avoid confusion, the **paint inventory** surfaces in the UI as the **"Paint Shelf"** (or "Paints"), and guide browsing is the **"Guides"** library. Backend tables are namespaced (e.g., a paint\_\* / guide\_\* prefix or a dedicated module package) so they're unmistakable next to STL-Inventory's model/tag tables.

### 3.4 Authoring now, public reader deferred

v1 is the **authoring module** (Brent only). Published guides leave the system as **downloadable PDFs** (the Patreon distribution channel), so no public website is needed yet — see Section 16. "Publish" means: mark the guide published, run final validation, and make its **PDF** available (single or bundled). A public reader is designed-for but deferred; the schema already supports it.

  

## 4\. Core features

### 4.1 Guide authoring (hybrid AI draft → human edit)

The signature workflow. Steps:

  

1.  **Start a guide.** Brent enters: figure name, franchise/source, scale (1:6, 1:12, 75mm, 28mm, bust), application methods (airbrush/brush/both + nozzle sizes), sections needed (skin, armor, cloth, metals, base…), and any special challenges (OSL, NMM, blood).
2.  **Acquire a reference image** (Section 4.4) — this feeds both the AI draft and the color-match studio.
3.  **AI draft.** Backend calls the generation service (Claude, wrapping the figure-painting skill's rules) to produce a structured draft: tabs, phases, step cards, swatches with codes/hex/value%, mix ratios, tips, warnings. **Output is structured JSON, not HTML** (see Section 9).
4.  **Validation pass (automatic).** Before the draft ever reaches the editor, the backend runs the validators (Section 8.4): every swatch's paint code is checked against the code-convention rules and confirmed present in inventory; the color-accuracy checklist (skin anchor band, highlight direction, white/black rule) runs and attaches flags.
5.  **Human edit.** Brent edits in a structured editor — reorder steps, swap paints (with inline inventory autocomplete + live hex chip), adjust value%, accept/reject AI flags, edit prose. Live preview renders the guide exactly as it will publish.
6.  **Publish.** Sets status published, assigns/creates the category, wires series links, and produces the downloadable **PDF** (single or part of a series bundle) ready to post to Patreon.

  

**Guardrail:** the AI draft is *always* a draft. There is no "auto-publish." This matches your skill's existing "ask, never assume" and "flag errors explicitly" rules.

### 4.2 Paint inventory (the load-bearing core)

  - **Canonical store** of every paint Brent owns: brand, line, code, name, approximate hex, and metadata (finish, special-handling flags like the enamel/Transparent-Red warnings).
  - **CSV import/export in PaintRack format.** The inventory is seeded from, and round-trips to, the PaintRack paintRack\_export\_YYYY-MM-DD\_HH-MM-SS.csv shape. Re-importing a newer export performs a **diff** (added/removed/changed) — never a blind overwrite — mirroring your "always ask for the previous CSV" memory rule.
  - **Color chips** rendered from the stored hex, exactly like the PDF swatch charts and the .swatch-dot in guides.
  - **Code-convention validation** baked in (e.g., Pro Acryl MPA-\#\#\# / MPA-S\#\# / AMP-\#\#\# / MEA-\#\#\#, Army Painter, etc.), so a typo'd code is caught at entry.
  - **Brand/line grouping** in the UI to match the inventory's structure (Pro Acryl Standard / Signature / AMP / Expert, Army Painter Fanatic / Speedpaint 2.0, FW Inks, VMC, etc.).

### 4.3 Color-match studio ("artist's rendering for color matching")

Given a reference image, help Brent pick paints:

  

  - **Eyedropper / region sampling.** Click or marquee a region of the reference; the app computes the average color (in CIE Lab, not raw RGB averaging) of that region.
  - **Nearest-paint suggestions.** Rank owned paints by perceptual distance (CIEDE2000) to the sampled color, returned as an ordered list of candidates with hex chips and codes — *suggestions Brent confirms*, never auto-applied.
  - **Value-aware mode.** Because the philosophy is *values first*, the studio also reports the sampled region's **value (L\*)** and can match on value alone (for building a value ladder) independent of hue. This is a first-class feature, not an afterthought.
  - **Palette extraction.** Optionally extract a small dominant-color palette from the whole image (k-means in Lab space) as a starting point for the guide's sections.

### 4.4 Reference image acquisition — the fallback chain

This directly answers your follow-up about renders, web search, and "maybe the user can provide a Google image search result." The app tries, in order, and stops at the first that succeeds:

  

0\. STL MODEL FOLDER IMAGE  ← free, because we're inside STL-Inventory

  

   If the guide is linked to a model, its existing folder thumbnail(s)

  

   are offered first — the render you printed from is often the best

  

   color reference available, and it's already indexed.

  

        │  (if no linked model / no image)

  

        ▼

  

1\. ARTIST / MANUFACTURER RENDER

  

   Brent pastes/uploads the official sculpt render or box art

  

   (Hot Toys, Mezco, the 3D artist's promo image, etc.).

  

        │  (if none available)

  

        ▼

  

2\. WEB RESEARCH (assisted, see feasibility note below)

  

   Backend searches for "\<figure\> \<manufacturer\>" official photos /

  

   film stills and presents candidates for Brent to pick from.

  

        │  (if search unavailable or no good result)

  

        ▼

  

3\. AI-GENERATED RENDERING

  

   An image model generates a reference rendering of the figure,

  

   used as the color target. Clearly labeled "AI reference."

  

        │  (if unsuitable)

  

        ▼

  

4\. USER-SUPPLIED IMAGE  ← your suggestion

  

   Brent pastes a URL from a Google image search result, or

  

   uploads a file directly. Always available as the final fallback.

  

**Feasibility note on web search (your "I'm not sure that's possible").** Server-side automated image search is possible but constrained:

  

  - It requires a **search provider with an API** — e.g., a Bing/Brave/SerpAPI-style image search endpoint, or the Claude API's web-search tool. Plain scraping of Google Images is brittle and against ToS, so we don't do that.
  - Results quality is uneven, and licensing matters for anything public-facing. So **step 2 is "assisted," not "automatic"**: the backend fetches *candidates*, Brent picks one, and we record attribution.
  - Because step 2 is the flaky one, steps 1 and 4 (human-supplied image) are the dependable spine. The architecture treats web search as a *nice-to-have accelerator*, with manual supply always available. This is the safe design given the uncertainty.

  

Every reference image stores its **provenance** (artist render / web / AI-gen / user upload) and an attribution/source URL, shown as a small credit in the guide hero.

### 4.5 Library organization — grouping & cross-linking

This preserves and formalizes your current index.html + by-category/ + series-badge model. In v1 it powers the **admin library** (browsing/managing your guides) and **PDF bundling**; the same data drives the public gallery when it lands later.

  

  - **Category grouping.** Guides belong to a category (film-tv, comics, dnd-animated-series, anime-music, wargaming, plus new ones as needed). The admin library groups by category, and PDF bundles can be exported per category. **New categories are created in data, not by editing HTML** — solving the "always update index.html" chore.
  - **Series cross-linking.** Guides can belong to a **series** (e.g., the 1966 Batman set, the D\&D animated cast). The series renders as the existing **series-badge** row in the guide (and print/PDF): the current guide as an active chip, siblings as links. Driven by a relation, not hand-authored anchors. A series is also the natural unit for a **bundled PDF reward**.
  - **Search & filter** (admin) by name, category, scale, paint line, technique tag.
  - **Reader/preview** reproduces the guide tabs, swatches, value maps, skills tabs, and the auto-built Thinning Reference exactly as today — used for the editor's live preview and as the source for print/PDF.

### 4.6 Print / export / PDF

  - **Print view** using the existing print.css.
  - **Downloadable PDF (Patreon reward).** A published guide can be rendered to a high-fidelity PDF driven by the existing print.css, downloaded as a file, and uploaded to Patreon as a subscriber reward. Because the PDF reuses the *same* print stylesheet as the browser print view, what Brent sees in print preview is what the PDF looks like — no separate PDF layout to maintain. Details in Section 9.4.
      
      - **Reward variants (optional):** the PDF generator can stamp a small "Patreon exclusive — thanks for supporting brent\_the\_programmer" footer line and/or a subscriber-tier label, configurable per export. Watermarking is available but off by default.
      - **Per-guide or batch:** export one guide, or a whole series/category as a single bundled PDF (e.g., the full D\&D animated cast as one reward drop).
  - **Static HTML export.** A guide can also be exported to a self-contained HTML file matching the *current* format — so the new system stays backward-compatible with the existing painting-guides/ archive and you never lose the portable-file option. (See Section 9.4.)

### 4.7 Feature flags & generation options (so anyone can use it)

The module ships in STL-Inventory's public builds as a **general-purpose feature**, not a Brent-only tool — so other makers can author their own guides and Patreon rewards. That means capabilities are **opt-in**, gated two ways:

  

  - **Module-level toggle (Settings).** A single "Enable Painting Guides" switch. Off by default in public builds until the user turns it on, so it never clutters the app for makers who only want the STL catalog.
  - **Capability gates (automatic).** AI draft, AI image-gen, and assisted web search each light up only when the user has supplied the relevant **own API key** (Section 14.2). No key → that capability is hidden/disabled, and the manual path remains.
  - **Per-guide generation checkboxes.** On the start-a-guide wizard and the export panel, the user picks what to use for *this* guide:
      
      - ☐ *Use AI to draft this guide* (needs Claude key) — unchecked = author from scratch.
      - ☐ *Generate a reference image with AI* (needs image key).
      - ☐ *Search the web for reference candidates* (needs search key).
      - ☐ *Add a Patreon reward stamp on export* — with sub-options for footer note / tier label / watermark (Section 9.4). Off by default; each user supplies their own footer text, so nothing of Brent's is hard-coded.

  

This keeps the feature genuinely reusable: a stranger who installs STL-Inventory gets the painting module **inert and key-less** until they opt in with their own credentials and choices — and none of Brent's keys, paint-data paths, or Patreon branding ship with it.

  

## 5\. Information architecture & routes

### 5.1 Admin routes (v1 — auth-gated)

|  |  |
| :-: | :-: |
| \*\*Route\*\* | \*\*Purpose\*\* |
| / | Dashboard: drafts, recently published, validation warnings |
| /library | Browse all guides grouped by category/series |
| /guides/new | Start-a-guide wizard |
| /guides/:id/edit | Structured guide editor + live preview |
| /guides/:id/draft | AI draft generation + diff view |
| /guides/:id/print | Print-optimized preview (source for PDF rendering) |
| /inventory | Paint inventory manager (table + chips) |
| /inventory/import | PaintRack CSV import + diff review |
| /color-match/:guideId | Color-match studio |
| /images | Reference image library |
| /export | PDF download / series-bundle builder |

### 5.2 Public routes (deferred — Section 16)

When the public gallery is built: /, /category/:slug, /guide/:slug (reader), /search, /about. The print view and :slug.pdf download already exist in the backend, so they carry over unchanged.

  

## 6\. Data model

The model is the contract. Everything else (API, UI, validators) derives from it. These tables live in **STL-Inventory's existing SQLite database** (so they ride along in its backup/restore). Two SQLite-specific notes: there is no native array type, so text\[\] fields below are stored as **JSON columns**; and jsonb likewise maps to a **JSON/TEXT column**. Primary keys follow STL-Inventory's existing convention (integer or UUID — match the host app rather than this doc). Tables are namespaced (paint\_\*, guide\_\*) to sit cleanly beside STL-Inventory's model/tag tables.

### 6.1 Entity overview

Category 1───\* Guide \*───1 Series (optional)

  

                 │  └───0..1 Model  (STL-Inventory's existing model table)

  

                 ├──\* Tab ──\* Phase ──\* Step ──\* Swatch \*──1 Paint

  

                 │     │                    └──\* MixComponent \*──1 Paint

  

                 │     ├── value\_map   (JSON block: 5 chips)

  

                 │     ├── skin\_config (JSON block: 3 method cards, on Skin tab)

  

                 │     └── metals\_config (JSON block: TMM + optional NMM)

  

                 ├──1 ReferenceImage

  

                 ├── character\_brief (JSON block on guide)

  

                 ├── theme           (JSON block on guide: :root vars + hero gradient)

  

                 └── thinning\_config (JSON block on guide: GUIDE\_THINNING analog)

  

Paint \*───1 PaintLine \*───1 Brand

  

ColorMatchSession \*───1 ReferenceImage, \*───\* Paint (candidates)

  

The only cross-module relation is Guide → Model (a nullable FK into STL-Inventory's existing model table). Everything else is self-contained in the painting tables.

  

**Design principle — relational core, JSON display blocks.** The Tab→Phase→Step→Swatch/MixComponent spine is **relational**, because validators must walk every swatch and the editor swaps paints in place. The fixed-shape display furniture that's only ever rendered as a unit — the value map, the three skin-method cards, the metals config, the character brief, the per-guide theme, and the thinning config — are stored as **JSON blocks** (SQLite JSON columns) on their owning row. This avoids over-normalizing things that never need a query, while keeping the parts that *do* need querying fully relational. **Every** **paint\_id** **reference, even inside a JSON block, is still validated** (the validator knows which JSON keys hold paint IDs — see Section 8.4).

### 6.2 Core tables

**brand** — id, name (Monument Hobbies, Army Painter, Vallejo, …)

  

**paint\_line** — id, brand\_id, name (Pro Acryl Standard, Signature Series, AMP, Expert Acrylics, Warpaints Fanatic, Speedpaint 2.0, VMC, FW Inks…), code\_pattern (regex used for validation, e.g. ^MPA-\\d{3}$).

  

**paint** — the inventory atom.

  

id              pk

  

paint\_line\_id   fk -\> paint\_line

  

code            text         -- "002", "S18", "AMP-008", "77.702"

  

name            text         -- "Coal Black", "Heavy Warm White"

  

hex             char(7)      -- "\#2A2A2A" approximate swatch color

  

value\_pct       smallint     -- 0..100 approximate L\*-derived value, nullable

  

finish          enum(matte,satin,gloss,metallic,ink,wash,fluor,primer,medium,pigment,texture)

  

matchable       bool         -- derived from finish: true only for opaque color paints (Section 8.6)

  

owned           bool         -- true = in inventory; false = known-but-not-owned

  

handling\_flags  jsonb        -- \["enamel","transparent-red-magenta-warning", ...\]

  

substitute\_for  uuid\[\]       -- optional: paints this can sub for

  

notes           text

  

source          text         -- "PaintRack 2026-05-29" | "manual"

  

**category** — id, slug (film-tv), display\_name, sort\_order, description.

  

**series** — id, slug, display\_name. (e.g., "Batman 1966", "D\&D Animated Series cast")

  

**guide**

  

id               pk

  

slug             text unique         -- "robocop-1987"

  

title            text                -- "RoboCop"

  

category\_id      fk -\> category

  

series\_id        fk -\> series null

  

model\_id         fk -\> model null    -- STL-Inventory model this figure was printed from

  

scale            enum(1:6,1:12,75mm,28mm,bust,other)

  

status           enum(draft,in\_review,published,archived)

  

franchise        text

  

creator\_credit   jsonb               -- {name, url}  (manufacturer/sculptor, NOT Brent)

  

reference\_image\_id fk -\> reference\_image null

  

light\_source     text                -- temperature/direction note

  

philosophy\_note  text                -- value-first brief

  

paint\_lines\_used text\[\]              -- denormalized for the paint bar + filtering

  

technique\_tags   text\[\]              -- \["OSL","NMM","blood","TMM"\] for filtering

  

thinning\_config  jsonb               -- GUIDE\_THINNING.airbrushRows etc.

  

created\_at, updated\_at, published\_at

  

**tab** — id, guide\_id, name ("Skin", "Armor", "Metals"…), sort\_order, has\_expert\_subtab bool.

  

**phase** — id, tab\_id, label ("Zenithal Sequence"), sort\_order. (Renders as .phase-label.)

  

**step**

  

id            pk

  

phase\_id      fk -\> phase

  

title         text

  

technique\_tag enum(airbrush,brush,wash,finish,effects,filter)  -- the colored pill

  

body          text            -- instructions incl. explicit value intent

  

value\_intent  text            -- structured "should read \~85% value" note

  

tip           text null       -- .tip green callout

  

warning       text null       -- .warning red callout

  

ratio\_box     text null       -- "4:1 Bold Pyrrole Red 003 to Orange 007"

  

sort\_order    int

  

**swatch** — a paint reference inside a step.

  

id          pk

  

step\_id     fk -\> step

  

paint\_id    fk -\> paint        -- MUST resolve to an owned paint

  

value\_pct   smallint           -- role value at this usage

  

role\_label  text               -- "mid-tone base", "final specular"

  

sort\_order  int

  

**mix\_component** — for multi-paint mixes (replaces old .mix/.plus/.ratio): id, step\_id, paint\_id, parts (numeric), sort\_order. The ratio string is derived from parts.

  

**reference\_image**

  

id            pk

  

guide\_id      fk null

  

storage\_key   text             -- local image volume path (shared with STL-Inventory)

  

provenance    enum(stl\_model\_folder, artist\_render, web\_research, ai\_generated, user\_upload)

  

source\_url    text null        -- attribution

  

alt\_text      text

  

width,height  int

  

created\_at

  

**color\_match\_session** — id, guide\_id, reference\_image\_id, samples jsonb (list of {region, lab, value, candidate\_paint\_ids\[\]}), created\_at.

### 6.3 Why structured, not HTML

Storing guides as the relational/JSON structure above (rather than HTML blobs) is what unlocks: validation, inventory swaps with live chips, the color-match loop, filtering by tag/scale/paint-line, series linking by relation, and clean multi-target rendering (web reader, print, static-HTML export). HTML is an **output**, never the source of truth.

### 6.4 The JSON display blocks (shapes)

These are the fixed-shape blocks referenced in the diagram. Shapes shown as TypeScript-ish for clarity; they're Pydantic models on the backend and the same generated TS on the frontend.

  

**character\_brief** (on guide) — the .char-brief block:

  

{ philosophy: string,            // value-first intent for this figure

  

  light\_source: string,          // "warm key, upper-left" — temperature + direction

  

  priority\_materials: string\[\] } // ordered focus list, e.g. \["skin","leather","gold"\]

  

**theme** (on guide) — replaces the hand-written per-guide :root + .hero block:

  

{ bg, surface, surface2, surface3, border, text, text\_muted, text\_dim, accent: hex,

  

  hero\_gradient: string }        // CSS gradient for .hero; injected as inline custom props

  

**value\_map** (on tab, optional) — the 5-chip greyscale ladder:

  

{ chips: \[ { hex, value\_pct, zone\_label } x5 \] }   // "deep shadow" … "specular"

  

**skin\_config** (on the Skin tab) — all three canonical methods must be present (memory rule), one flagged recommended:

  

{ recommended: "basic" | "pinkle" | "wash\_tinting",

  

  anchor\_paint\_id: id,           // the validated mid-tone anchor (Section 8.4)

  

  complexion\_band: enum,         // drives anchor/highlight validation

  

  freckling\_note: string | null,

  

  methods: \[

  

    { key, title, recommended: bool,

  

      steps: Step\[\] }            // each method is a mini step-sequence (same Step shape)

  

  \] }

  

**metals\_config** (on a Metals tab) — TMM primary, NMM optional:

  

{ tmm: { approach: "gloss\_black\_1to6" | "standard\_small", steps: Step\[\] },

  

  nmm: { steps: Step\[\] } | null }   // present only when NMM sub-tab is added

  

**thinning\_config** (on guide) — the GUIDE\_THINNING analog consumed by the data-driven Thinning Reference (Section 9.3). Static rows/cards are injected by the component; this holds only the figure-specific additions:

  

{ airbrush\_rows: \[ { technique, nozzle, ratio, behavior } \],

  

  brush\_rows:    \[ { technique, ratio, behavior } \],   // optional

  

  thinning\_cards:\[ { title, body } \] }                 // optional

  

**Note (figure-only v1):** these shapes cover the figure-painting guide type. The wargaming-painting type is **not built in v1**, but its extension is fully designed in Section 6.6 so the decision is de-risked.

### 6.5 The GuideDraft contract

GuideDraft is the **single structured object** the AI generation service emits, the editor mutates, and the renderers consume. It's the assembled tree of everything above. The full shape is in **Appendix A**; in brief:

  

GuideDraft = Guide-header fields

  

           + character\_brief + theme + thinning\_config

  

           + tabs: \[ Tab { value\_map?, skin\_config?, metals\_config?,

  

                           phases: \[ Phase { steps: \[ Step {

  

                             swatches: \[Swatch\], mix: \[MixComponent\],

  

                             tip?, warning?, value\_intent } \] } \] } \]

  

           + reference\_image\_ref

  

           + validation\_flags: \[\]   // populated by the validator, not the AI

  

The AI returns GuideDraft with validation\_flags empty; the validator fills them; the editor resolves them. A guide can only reach published when no block-severity flag remains (Section 8.4).

### 6.6 Wargaming extension (designed, not built in v1)

You already have a wargaming-painting skill, a wargaming-guide-template.html, and **12 wargaming guides** in the corpus — so this isn't hypothetical, it's a known second guide type. v1 stays figure-only, but the design below makes adding it a **bounded, additive change** rather than a rewrite. **Recommendation: ship figure-first; add wargaming after the 12 wargaming guides import (M5) and show concretely what extra structure they need** (Section 9.7). Deciding on evidence beats guessing now.

  

How it slots in when the time comes:

  

  - **Discriminator:** add guide.guide\_type = "figure" | "wargaming" (default figure). Nothing else changes for existing guides.
  - **Shared core, unchanged:** Tab → Phase → Step → Swatch/MixComponent, the Paint Shelf, validation (paint.exists, code patterns, white/black rule, Transparent-Red), color match, PDF/print, and the importer all apply identically. Wargaming doesn't fork the engine.
  - **Type-specific JSON blocks** (parallel to the figure blocks, same pattern):
      
      - quality\_tiers — the Tabletop-Ready / Battle-Ready / Display tracks, as parallel step-sequences per surface.
      - batch\_workflow — the assembly-line ordering for painting many models at once.
      - basing — base materials/steps (your paint-inventory already catalogs the Folk Art basing palette + texture pastes).
      - army\_cohesion — notes for keeping a unit visually unified.
  - **Renderer:** the reader/print components branch on guide\_type to show tier tracks and batch/basing blocks; guide.css already styles both (the wargaming template exists). The figure value-map/skin/metals blocks simply aren't present on wargaming guides, and vice-versa.
  - **AI + validation:** the generation prompt swaps in the wargaming rules (from the wargaming-painting skill); validators gain a few tier/basing structural checks. Same machinery, different rule data.

  

Net: a guide\_type column, a handful of extra JSON shapes, a renderer branch, and a second rule set — no disturbance to the relational core, the inventory, or the publishing pipeline. That's why deferring it costs nothing.

  

## 7\. API design (REST, FastAPI)

JSON, mounted on **STL-Inventory's existing FastAPI app** under a painting namespace (e.g., /api/painting/...; shown below as /api/v1/... for brevity). It reuses the host app's auth/session and its scan-style job/polling pattern rather than introducing new infrastructure.

### 7.1 Read endpoints (admin library now; reused by the public site later)

GET  /api/v1/categories                      -\> \[{slug, name, guide\_count}\]

  

GET  /api/v1/categories/:slug/guides         -\> \[guide cards\]

  

GET  /api/v1/guides?scale=\&tag=\&line=\&q=     -\> filtered guide cards

  

GET  /api/v1/guides/:slug                     -\> full rendered guide payload

  

GET  /api/v1/series/:slug                     -\> series + member guides (for badges)

### 7.2 Admin — guides

POST   /api/v1/admin/guides                   -\> create (wizard inputs)

  

GET    /api/v1/admin/guides/:id               -\> full editable guide

  

PATCH  /api/v1/admin/guides/:id               -\> partial update (any field/step/swatch)

  

POST   /api/v1/admin/guides/:id/draft         -\> trigger AI draft (async job)

  

GET    /api/v1/admin/guides/:id/validate      -\> run validators, return flags

  

POST   /api/v1/admin/guides/:id/publish       -\> status -\> published

  

POST   /api/v1/admin/guides/:id/export        -\> static HTML export (returns file)

  

POST   /api/v1/admin/guides/:id/pdf            -\> render PDF via print.css (async job -\> file)

  

POST   /api/v1/admin/export/pdf-bundle         -\> {guide\_ids|series\_id|category\_id, options} -\> bundled PDF

  

PDF/bundle options: {watermark?: bool, footer\_note?: string, tier\_label?: string}.

### 7.3 Admin — inventory

GET    /api/v1/admin/paints?line=\&q=          -\> inventory (autocomplete source)

  

POST   /api/v1/admin/paints                    -\> add paint (validates code pattern)

  

PATCH  /api/v1/admin/paints/:id

  

POST   /api/v1/admin/inventory/import          -\> upload PaintRack CSV -\> diff preview

  

POST   /api/v1/admin/inventory/import/confirm  -\> apply chosen diff

  

GET    /api/v1/admin/inventory/export.csv      -\> PaintRack-format export

### 7.4 Admin — images & color match

POST   /api/v1/admin/images                    -\> upload (multipart) | {url} | {ai\_prompt}

  

GET    /api/v1/admin/images/search?q=          -\> assisted web image candidates

  

POST   /api/v1/admin/color-match/sample        -\> {image\_id, region} -\> {lab, value, candidates\[\]}

  

POST   /api/v1/admin/color-match/palette       -\> {image\_id, k} -\> palette\[\]

### 7.5 Async jobs

AI draft, AI image generation, and PDF render are slow; run them as background jobs using **the same pattern STL-Inventory already uses for its library scan** (in-process async + status polling — no new queue infra). POST …/draft returns a job\_id; the client polls GET /api/v1/admin/jobs/:id for progress, mirroring the existing scan UI.

  

## 8\. Backend architecture (Python)

### 8.1 Stack — inherited from STL-Inventory

  - **FastAPI** — the painting routers are added to STL-Inventory's existing app, not a new service.
  - **SQLAlchemy + SQLite** — same engine and DB file as the host app (so painting data is in its backups). JSON columns for the semi-structured bits (thinning\_config, handling\_flags, array-like fields). Follow STL-Inventory's existing migration approach (it ships schema changes with the app and supports backup/restore); don't bolt on a different migration tool.
  - **Pydantic** schemas as the single source of truth for request/response shapes — these mirror Section 6 and generate the TypeScript types for the frontend.
  - **Image storage:** the same local image volume STL-Inventory already mounts (no S3 needed locally).
  - **Background jobs:** the host app's existing in-process async + polling pattern (the scan pipeline) — no Celery/Redis.
  - **Added dependencies (painting-only):** **Pillow / NumPy / scikit-image** for color math (Lab, CIEDE2000, k-means), **Playwright + Chromium** for PDF, and the **Claude SDK** for AI drafts. These are additive to STL-Inventory's requirements.

### 8.2 Service layout (a painting/ package within the STL-Inventory backend)

backend/painting/            \# new module package inside the existing backend

  

  routers/          \# FastAPI routers, included by the host app's main router

  

  schemas/          \# Pydantic models (the contracts)

  

  models.py         \# SQLAlchemy ORM (paint\_\*, guide\_\* tables; FK to existing model)

  

  services/

  

    generation.py   \# AI draft: prompt assembly + Claude call + parse to schema

  

    validation.py   \# code-convention + inventory + color-accuracy checks

  

    inventory.py    \# PaintRack CSV import/diff/export

  

    colormatch.py   \# Lab/CIEDE2000/k-means

  

    images.py       \# upload, AI-gen, assisted web search, STL-folder source, provenance

  

    pdf.py          \# print-view -\> Playwright -\> PDF (single + bundle)

  

    rendering.py    \# structured guide -\> static HTML export

  

  data/

  

    paint\_lines.yaml  \# code patterns + canonical line metadata

  

This keeps the painting concern self-contained and easy to reason about beside STL-Inventory's existing model/scan code, while sharing the app, DB session, auth, and job runner.

### 8.3 Generation service (the AI draft)

  - Wraps the **domain rules currently in the** **figure-painting** **SKILL.md** — value-first philosophy, white/black rule, skin-method decision table, paint-line priority, swatch/value conventions — as a **system prompt + structured-output schema**. The LLM is asked to emit JSON matching our GuideDraft Pydantic schema (**Appendix A**), *not* prose or HTML.
  - **Inventory is injected into the prompt** (or exposed as a tool the model can query) so the model can only choose from owned paints. Post-generation, the validator hard-enforces this anyway.
  - **Key-gated:** the service resolves the Claude key (env → Settings, per Section 14.2) and is only reachable when a key is present and the per-guide "Use AI to draft" box is checked. No key / unchecked → the endpoint is disabled and the UI offers manual authoring only.
  - Two pluggable generation backends behind one interface:

<!-- end list -->

1.  **Direct Claude API call** with the rules as system prompt (recommended — full control, structured output).
2.  **The existing skill**, invoked as-is, with an HTML→structure parser. (Heavier; useful as a migration bridge / fallback.)

#### 8.3.1 Prompt architecture

Three inputs assemble each request:

  

1.  **System prompt = distilled SKILL.md** — value-first philosophy, the white/black rule, the skin-method decision table, paint-line priority order, swatch/value conventions, and the inclusive-language tone rules. This is **authored and versioned in** **painting/data/generation\_prompt.md** — the *same* source the validator's rules derive from, so the painting truth lives in one place (Section 12). Budget: **\~3–5k tokens**, static, cacheable via prompt caching.
2.  **Figure context** — the wizard inputs (name, scale, methods, sections, challenges), the reference image (or its analysis), and the resolved complexion\_band. Small: **\~0.5–1k tokens**.
3.  **One abridged few-shot exemplar** — a single GuideDraft from the corpus (Section 9.7) chosen to match the figure's profile (skin-heavy → Cassie; metal-heavy → RoboCop). **Abridged** (one representative tab, not the whole guide) to keep it **\~2–4k tokens** rather than 8k+. House style by example beats house style by description.

#### 8.3.2 Inventory injection — as a tool, not a dump

The full inventory (17 brands, hundreds of paints) is too large and too noisy to paste into every prompt. Instead, expose it as a **tool the model calls**:

  

search\_paints(query?, line?, finish?, value\_range?) -\> \[{paint\_ref, name, value\_pct, finish}\]

  

The model pulls only the paints it needs for the surface it's working (e.g., warm flesh tones in the 40–60% value band), keeping the prompt lean and the choices grounded. A compact **"preferred palette" summary** (the Pro Acryl standard line as code+name+value, \~1k tokens) is still inlined as a starting hint. Either way, the **validator hard-enforces** owned/matchable/code-pattern afterward — the tool guides the model, the validator guarantees correctness.

#### 8.3.3 Structured output + repair loop

  - Request **structured output** (tool-use / JSON mode) bound to the GuideDraft schema (Appendix A) so the model returns parseable JSON, not prose.
  - On a parse or schema-validation failure, run **one bounded repair pass**: re-prompt with the offending error and ask for a corrected object. After N=2 failed repairs, surface to Brent rather than loop.
  - After a valid parse, run the **content validator** (Section 8.4). If block flags remain, optionally feed them back for **one auto-repair attempt** (e.g., "the skin anchor is too light for deep\_dark — choose from these candidates"), then hand to the human regardless. The AI never escapes the validate→repair→human gate.
  - **Temperature:** low (≈0.3) — structure and paint choices should be stable and grounded; the prose has room without needing high randomness.

#### 8.3.4 Token budget & chunked generation

Rough per-guide envelope: system \~4k + context \~1k + exemplar \~3k + tool round-trips \~2k = **\~10k input**; a full multi-tab GuideDraft output is **\~6–12k tokens**. That fits comfortably in-context, but **large guides (7+ tabs) generate more reliably tab-by-tab**: produce the guide skeleton (header, brief, theme, tab list) first, then generate each tab's GuideDraft fragment in its own call, and assemble server-side. This mirrors the skill's existing "split big guides into two writes" rule, trades a little latency for much higher structural reliability, and keeps any single response small enough to validate and repair cleanly. Small guides (≤6 tabs) generate in one shot.

#### 8.3.5 Cost, latency, privacy

Generation is an **async job** (Section 7.5) with progress polling. It runs on the **user's own Claude key** (Section 14.2) — so cost is the user's, and nothing routes through Brent. Prompt caching on the static system prompt keeps repeat-generation cheap. A typical guide is a few cents and a handful of seconds per tab; the chunked path is bounded and predictable.

### 8.4 Validation service (non-negotiable)

Runs on every draft and before every publish. Returns structured flags, **never silently mutates**. Each flag: { rule\_id, severity: warn|block, message, location, suggestion? }. A guide reaches published only when no block flag remains (or Brent explicitly overrides a warn).

  

**Rules are data, not hard-coded** **if****s.** The checks live in a versioned **validation\_rules.yaml** (Appendix B) plus a small amount of structural code. This is what lets the SKILL's painting truth and the validator stay one source instead of two. The rule set:

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*rule\\\_id\*\* | \*\*Severity\*\* | \*\*What it checks\*\* |
| paint.exists | \*\*block\*\* | Every paint\\\_id (incl. inside JSON blocks) resolves to an owned = true paint. |
| paint.code\\\_pattern | \*\*block\*\* | Each paint's code matches its line's code\\\_pattern (encodes paint-code-conventions.md). |
| skin.anchor\\\_band | \*\*block\*\* | The Skin tab's anchor\\\_paint\\\_id sits in the band that matches complexion\\\_band (table below). Catches the Diana-the-Acrobat failure. |
| skin.highlight\\\_direction | warn | Highlight paints shift the correct way for the band (warm-golden on deep skin, not pink/cream). |
| value.white\\\_black\\\_rule | warn | Pure white only as a final-specular swatch; pure black only in permitted roles; shadow anchor is Payne's Grey, not black. |
| value.range | warn | Per tab, darkest and lightest swatch values differ by ≥ a scale-dependent threshold (value not compressed). |
| glaze.transparent\\\_red | warn | Any thinned/glazed Transparent Red → suggest \*\*FW Crimson Ink\*\* (your memory rule). |
| structure.thinning\\\_last | \*\*block\*\* | Thinning Reference is the final tab. |
| structure.trouble\\\_grid\\\_even | warn | Trouble-grid card count is even (Tip-Dry is auto-injected → author 3 → 4 total). |
| structure.no\\\_empty\\\_tabs | \*\*block\*\* | No empty/placeholder tab or phase. |
| structure.no\\\_legacy\\\_mix | warn | No legacy .mix/.plus/.ratio patterns; mixes use mix\\\_component. |

  

**Skin complexion-band → anchor table** (drives skin.anchor\_band; lifted from the SKILL's Color Accuracy Checker so there's one source):

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*complexion\\\_band\*\* | \*\*Pro Acryl anchor\*\* | \*\*Army Painter Fanatic triad (hi · mid · shadow)\*\* |
| very\\\_fair | Shadow Flesh 042 / Bright Shadow Flesh S41 | Pearl · Opal · Ruby Skin |
| fair\\\_warm | Warm Flesh 073 / Peach Flesh | Barbarian · Agate · Moonstone Skin |
| medium\\\_tan | Advanced Flesh Tone S17 / Tan Flesh 024 | Leopard Stone · Tourmaline · Jasper Skin |
| warm\\\_olive | Olive Flesh 041 | Topaz · Tiger's Eye · Carnelian Skin |
| brown\\\_warm | Dark Warm Flesh S08 | Quartz · Dorado · Amber Skin |
| deep\\\_dark | Dark Flesh 068 | Mocca · Onyx · Obsidian Skin |

  

The validator flags when the chosen anchor's value sits in a *lighter* band than complexion\_band — the most common and most damaging error (a deep-skin character anchored on Shadow Flesh 042 reads as light caramel no matter what's layered on top).

  

**Known-failure regression cases** become validator test fixtures (Appendix B), so each fixed mistake stays fixed: Diana-the-Acrobat anchor too light; Diana highlight pink instead of warm-golden; Robin '66 tights painted green; Captain America boots as flat graphic red. Adding a new caught error = add a fixture.

### 8.5 Image service

  - **From linked STL model:** if the guide has a model\_id, list that model's indexed folder images and offer them as reference candidates (provenance stl\_model\_folder). Zero-cost, because STL-Inventory already cataloged them.
  - **Upload:** validate, store, record provenance user\_upload.
  - **From URL:** fetch a user-supplied URL (the Google-image-result fallback), store a copy, record provenance + source\_url.
  - **AI generation:** call an image model with a prompt built from figure name + description; store with provenance ai\_generated, clearly labeled.
  - **Assisted web search:** call a search-provider API for candidates; return thumbnails for Brent to choose; **never auto-select**. Degrades gracefully to "no results — please supply an image" when no provider is configured. (This is the honest answer to the feasibility question.)

### 8.6 Color-match service — honest by design

The pipeline:

  

  - Decode region → convert sRGB → **CIE Lab** (D65). Average **in Lab** (perceptually correct), not RGB.
  - Rank candidate paints by **CIEDE2000** distance; also expose a **value-only** ranking on L\* for value-ladder building.
  - Palette extraction via **k-means in Lab space**, k configurable.

  

The honesty problem — **most of the inventory isn't hex-matchable.** A single flat hex is meaningful for opaque, matte/satin paints. It is *not* meaningful for:

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Class\*\* | \*\*Why a hex lies\*\* | \*\*Match behavior\*\* |
| \*\*Metallics\*\* (Silver, Gold, VMC range) | Appearance is reflectance + flake, not a flat color; a swatch hex can't capture it | \*\*Excluded\*\* from hue match; matched by \*\*value only\*\* (they still have a value role) |
| \*\*Inks / washes\*\* (FW, Nuln Oil, Pro Acryl washes) | Transparent — final color depends on what's beneath | \*\*Excluded\*\* from hue match; surfaced separately as "shade/glaze options" |
| \*\*Transparents\*\* (Pro Acryl 046–053, 064) | Glaze modifiers, not basecoats; the Transparent-Red→magenta trap lives here | \*\*Excluded\*\*; cross-referenced to the validator's Transparent-Red rule |
| \*\*Fluorescents\*\* | Out-of-gamut; no honest sRGB hex exists | \*\*Excluded\*\* from hue match |
| \*\*Mediums / primers / pigments / textures\*\* | Not color choices at all | \*\*Excluded\*\* entirely from matching |

  

So paint carries a derived **matchable** flag (true only for opaque color paints). Hue match runs over owned = true AND matchable = true; the excluded classes are either value-only (metallics) or shown in a clearly-labeled secondary list (inks/glazes), never ranked as if they were a flat-color hit.

  

Confidence, stated plainly (ΔE2000 bands):

  

  - **ΔE \< 2** — "very close." **2–5** — "close, confirm by eye." **5–10** — "in the family." **\> 10** — "loose; shown for completeness."
  - Results always carry the band label and the caveat that **inventory hexes are approximate** (your memory note) — these are *suggestions to confirm by eye under your bench light*, never an auto-applied answer.

  

**Value-first alignment.** The default emphasis is the **value-only** ranking, because the philosophy is values-first and value is the one thing a flat hex *can* represent honestly even for metallics. Hue ranking is the secondary lens. The studio leads with "here's the value you sampled and the paints that sit at that value," then offers hue candidates underneath.

  

**Realistic expectation (success criterion S5, restated).** Target is "returns the correct owned paint *family* for a sampled opaque region in the majority of cases," not pixel-exact color science. Skin, cloth, and leather match well; metals and glazes are guided by value + role, not hue distance. The spec does not promise more than the data supports.

  

## 9\. Rendering strategy (preserving the existing look)

This is the subtle part: the in-app reader/preview (and the print/PDF output) must look like the current hand-built guides, which depend on guide.css, guide.js, and skills-reference.js. Note this reader lives *inside* STL-Inventory's React app but keeps the guides' own dark theme via scoped guide.css — it doesn't have to match STL-Inventory's Tailwind chrome.

### 9.1 Principle: one structure, four renderers

The guide's structured data renders to four targets, all sharing the **same CSS design tokens**:

  

1.  **React reader** (public web) — components that emit the same class names (.hero, .paint-bar, .tab-content, .swatch, .ratio-box, .phase-label, .tip, .warning) so guide.css styles them unchanged.
2.  **Print view** — same components, print.css applied.
3.  **PDF** — the print view rendered to a downloadable PDF (Patreon reward), driven by the same print.css. See 9.4.
4.  **Static HTML export** — server renders to a self-contained .html file matching today's format.

### 9.2 Reuse the existing CSS as the design system

guide.css becomes the canonical stylesheet for the React app (imported globally, or tokenized into CSS variables already present: --bg, --surface, --accent, --tag-\*, etc.). Per-guide theme colors (the :root block + .hero gradient today) become **guide-level theme fields** in the data model, injected as inline CSS custom properties on the reader root. This keeps the per-figure theming you already do, without hand-writing \<style\> blocks.

### 9.3 Port the JS behaviors to React

  - showTab() / showSubTab() → React state (active tab/subtab). No global functions, no localStorage (matches the skill's no-localStorage rule).
  - skills-reference.js (which injects the Thinning Reference tab, the zenithal/greyscale anchors, the Tip-Dry card) → a **React component** driven by the guide's thinning\_config data plus shared static content. The static rows/cards become constants in the component; GUIDE\_THINNING.airbrushRows becomes the guide's thinning\_config.airbrush\_rows.

### 9.4 PDF generation (Patreon rewards)

The PDF is produced from the **print view**, so print.css is the single source of layout truth — no separate PDF template to keep in sync.

  

  - **Engine: headless Chromium via Playwright.** The PDF service loads the /guide/:slug/print route in headless Chromium and calls "print to PDF." This gives the highest CSS fidelity (the same engine that renders the browser print preview), so swatch chips, value maps, and theme colors come out exactly right. Playwright + Chromium ships in the backend Docker image.
      
      - *Lighter alternative considered:* **WeasyPrint** (pure-Python, no browser). Rejected as the default because its CSS support is weaker (flex/grid quirks) and the guides lean on modern layout — but it's a viable fallback if we ever want to drop the Chromium dependency.
  - **Print view must expand all tabs.** The interactive reader shows one tab at a time; the print/PDF view must render **every tab and sub-tab expanded and in order** (skin, armor, metals, skills, thinning ref) so the PDF is the complete guide. This is a print.css + print-view-component requirement, called out so it isn't missed.
  - **Async + cached.** PDF render is a background job (a few seconds in Chromium); the result is cached and keyed on the guide's updated\_at, so re-downloading an unchanged guide is instant and editing invalidates the cache.
  - **Reward stamping.** Optional footer note / tier label / watermark are injected as print-only elements (a dedicated .patreon-stamp block shown only in print.css) before render.
  - **Bundling.** A series/category bundle concatenates each member's print view into one document (cover page optional) and renders once.

### 9.5 Static export keeps backward compatibility

services/rendering.py serializes a guide to the exact current HTML shape (linking the shared assets), so:

  

  - the existing painting-guides/ archive format still works,
  - you retain portable single-file guides,
  - migration can run both systems in parallel during transition.

### 9.6 The HTML importer

A one-time (re-runnable) importer parses the existing by-category/\*\*/\*.html guides into GuideDraft records. There are **38 guides today** (26 figure + 12 wargaming), all machine-generated from one template, so the DOM is **highly regular and deterministically parseable** — this is a tractable parser, not an ML problem.

  

**Engine:** Python + **BeautifulSoup** (or selectolax), keyed on the known class names. Direct DOM→field mapping:

  

|  |  |
| :-: | :-: |
| \*\*Source DOM\*\* | \*\*→ GuideDraft field\*\* |
| .hero .category / h1 / .subtitle / .film-ref / .creator-credit | header fields, creator\\\_credit |
| :root inline vars + .hero gradient | theme |
| .paint-bar .paint-pill | paint\\\_lines\\\_used |
| .char-brief | character\\\_brief |
| .tab-btn (showTab('id')) + .tab-content\\\#id | tabs\\\[\\\] |
| .phase-label | Phase.label |
| .step → .step-number class (airbrush/brush/…) | Step.technique\\\_tag |
| .swatch → .swatch-dot style background:\\\#hex; .swatch-name (name \*\*+ trailing code\*\*); .swatch-brand; .swatch-value (\\\~NN% value — role) | Swatch (+ resolve paint\\\_ref) |
| .ratio-box text ("Mix: 1:1 A + B — thin…") | Step.ratio\\\_box + best-effort mix\\\[\\\] |
| .tip / .warning (strip ✦ TIP: / ⚠ NOTE:) | Step.tip / Step.warning |
| .value-map .value-chip (.chip-swatch bg, .chip-val, .chip-label) | Tab.value\\\_map |
| .method-card (+ .recommended) | SkinConfig.methods\\\[\\\] |
| window.GUIDE\\\_THINNING = {…} JS block | thinning\\\_config |

  

**The genuinely lossy / best-effort bits** (flagged, not hidden):

  

  - **Name/code split.** "Black Primer P-002" → {name:"Black Primer", code:"P-002"} by matching the trailing token against the line code\_patterns. Ambiguous ones (e.g. a name ending in a number) get flagged for review.
  - **paint\_ref** **resolution.** Each parsed code is looked up in the **Paint Shelf**; a hit sets paint\_id, a miss raises a paint.exists flag in the import report (often it just means that paint isn't in the inventory yet — the report doubles as an inventory gap list).
  - **ratio-box** **→** **mix\[\]****.** Regex pulls "1:1 Warm Flesh 073 + Peach Flesh" into components where it can; otherwise the raw string is preserved verbatim in ratio\_box so nothing is lost.
  - **Skin/metals nuance.** Method cards and TMM/NMM blocks parse structurally; any prose that doesn't fit a field is kept as step body rather than dropped.

  

**Output contract:** the importer never writes silently. It produces, per guide, a GuideDraft **plus an import report** ({resolved, unresolved\_paints\[\], ambiguous\_codes\[\], unmapped\_nodes\[\]}). Import lands guides as **draft** **status** for human review, never auto-published.

  

**Round-trip golden test (the real payoff):** import a guide → render it back through the static-HTML exporter (Section 9.5) → diff against the original file. A clean round-trip proves two things at once: the **schema is complete** (nothing was lost) and the **renderer is faithful** (output matches the hand-built original). Divergences point precisely at the gap. This makes the importer the **acceptance test for the whole rendering layer**, not just a data-migration convenience.

### 9.7 The guide corpus as Code's ground truth

Beyond migration, the 38 existing guides are the **best available specification** — concrete, real, already-approved output. Put them to work across the build:

  

  - **Golden fixtures (M2).** Import 3–5 *diverse* guides early — one skin-heavy (Cassie Hack), one metal-heavy/TMM (RoboCop), one with OSL/blood, one NMM, one minimal — and use their round-trip diffs as the renderer's acceptance tests. Building the schema *against real guides* surfaces missing fields immediately, instead of discovering them after launch.
  - **Schema-coverage proof.** Run the importer across all 38 and collect every unmapped\_node. An empty set means the schema covers the real corpus; a non-empty set is a precise to-do list. This is objective evidence the data model is right.
  - **Few-shot examples for the AI (Section 8.3).** A handful of exemplary GuideDrafts become reference outputs in the generation prompt, so the AI matches your house style (value-first phrasing, swatch density, tip/warning voice) instead of inventing its own. The corpus is your style guide, in data form.
  - **Seed / demo data.** Importing populates the app with real content from day one — Code develops and demos against RoboCop and Cassie, not lorem ipsum. (For a shippable public build, seed with a tiny neutral sample instead of your full catalog.)
  - **Validator calibration (Section 8.4).** Run the validator over all imported guides. They're your *approved* work, so they should come back nearly clean — any block flag is almost certainly a **validator false-positive to tune**, and the rare real catch is a latent issue worth knowing. This is a free, high-quality calibration set, and a guardrail against an over-zealous validator blocking good work.
  - **Evidence for the wargaming decision.** The 12 wargaming guides reveal, concretely, whether the figure schema stretches to cover them or whether quality-tiers/batch/basing truly need their own structures — so the deferred wargaming-scope call (Section 17, Q-wargaming) can be made on data, not guesswork.

  

**Recommendation:** treat the importer not as an afterthought milestone but as the **schema's acceptance test, pulled into M2**. Full-corpus import + cleanup stays in M5, but a few golden fixtures should drive the rendering work from the start.

  

## 10\. Frontend architecture (React) — added to STL-Inventory's app

### 10.1 Stack — the host app's existing frontend

  - **React 18 + TypeScript + Vite + TailwindCSS** — STL-Inventory's stack. The painting screens are new routes/pages added to the same app, reusing its nav, card-grid, pagination, URL-driven filter state, and localStorage filter presets.
  - **Server state:** whatever STL-Inventory already uses for data fetching (add TanStack Query only if it isn't already present).
  - **Types generated from the backend Pydantic/OpenAPI** schema — frontend and backend never drift.
  - **Two styling worlds, intentionally:** admin chrome (Paint Shelf, wizard, editor, color-match studio) uses STL-Inventory's **Tailwind** look so it feels native to the app. The **guide reader/preview** consumes the **existing** **guide.css** **as-is** (scoped) so guides keep their dark, per-figure theme. The reader must not be re-styled into Tailwind.

### 10.2 Key components

**Reader/preview (also the print/PDF source):** GuideHero, PaintBar, CharacterBrief, SeriesBadge, ModelLink (back to the STL-Inventory model), TabBar + TabPanel, StepCard, SwatchRow (+ SwatchDot), RatioBox, ValueMap, MethodCards (skin), MetalsTab (+ NMM subtab), SkillsTab, ThinningReference (data-driven), GuideFooter (constant: brent\_the\_programmer + @stephenson913).

  

**Admin:** GuideWizard (incl. optional "link to model" picker), DraftDiffView (AI output vs current), StepEditor, SwatchPicker (Paint Shelf autocomplete + live hex chip + code validation), MixEditor, PaintShelfTable, CsvImportDiff, ColorMatchStudio (image canvas + eyedropper + candidate list + value readout), ImageLibrary (incl. the linked model's folder images), ValidationPanel (flags with accept/override).

  

**Added to existing STL-Inventory screens:** a "Painting Guide" affordance on the **model detail page** ("Create guide" / "View guide"), and a small "has guide" badge on model cards.

### 10.3 Color-match studio UX

Canvas with the reference image; click/marquee to sample; right rail shows the sampled chip, its Lab + value%, and a ranked candidate list of owned paints (hex chip · name · code · ΔE · value%). A "value-only" toggle re-ranks by L\*. "Add to step" pushes a chosen paint into the open guide's step as a swatch.

  

## 11\. Non-functional requirements

  - **Tone & language:** inclusive, caregiver-friendly. The app's own copy (and a linter on guide prose) avoids "easy," "no skill required," "anyone can." Encourage growth. This is a product value, enforced in content review.
  - **Accessibility:** dark theme is the default (workbench lighting), but ensure WCAG-AA contrast for text; swatch chips carry text labels (never color-only meaning); keyboard-navigable tabs; alt text required on reference images.
  - **Performance:** the admin app is single-user and local, so raw throughput isn't a concern; the one slow path is PDF rendering (headless Chromium) — handled as a cached async job (Section 9.4).
  - **Print/PDF:** print.css parity with current guides; PDF output is the published deliverable and must render every tab expanded (Section 9.4).
  - **Data safety:** paint CSV import is diff-reviewed, never blind-overwrite. Guides are versioned (at minimum updated\_at + soft-delete/archive; ideally a revision history). Because painting tables live in STL-Inventory's SQLite DB, they're **included in its existing backup/restore** for free — guides, paints, and links all snapshot together. **API keys are the deliberate exception:** they live in a separate secrets store and are **excluded from the shareable backup** (Section 14.2), so a backup can't leak credentials.
  - **Observability:** log AI draft requests/responses for debugging recipe quality; capture validation flag rates as a quality metric (success criterion S3).

  

## 12\. The Claude skill's future

The figure-painting skill doesn't have to die. Recommended relationship:

  

  - **Skill = a generation backend option** behind the app's generation interface (Section 8.3). The app's value-add is structure, validation, inventory grounding, color match, and publishing — none of which the skill does today.
  - The **domain rules** (SKILL.md) become the **authored prompt + validator rules** — versioned in app/data/ and code, so there's one source of painting truth rather than two drifting copies.
  - Net: the skill stays useful for quick one-off guides in chat; the app is the system of record and the publishing pipeline.

  

## 13\. Tech stack summary & rationale

Everything except the painting-specific additions is **inherited from STL-Inventory** — that's the point of building inside it.

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Layer\*\* | \*\*Choice\*\* | \*\*Source\*\* |
| Frontend | React 18 + TS + Vite + Tailwind | \*\*STL-Inventory (existing)\*\* |
| Reader styling | Existing guide.css (scoped) | Painting module — visual parity is a hard requirement |
| Backend | FastAPI (Python 3.12) | \*\*STL-Inventory (existing)\*\* |
| ORM / DB | SQLAlchemy + \*\*SQLite\*\* | \*\*STL-Inventory (existing)\*\* — painting tables join the same DB |
| Migrations | STL-Inventory's existing approach | \*\*STL-Inventory (existing)\*\* — don't introduce a second tool |
| Proxy / deploy | nginx + Docker Compose + standalone binary | \*\*STL-Inventory (existing)\*\* |
| Backup / restore | .db snapshot | \*\*STL-Inventory (existing)\*\* — painting data included free |
| Jobs | In-process async + polling (scan pattern) | \*\*STL-Inventory (existing)\*\* |
| Tests / CI | pytest (in-memory SQLite) + GitHub Actions | \*\*STL-Inventory (existing)\*\* — painting tests join the suite |
| Color math | NumPy + scikit-image | Painting module (new dep) |
| Images | Pillow + the existing local image volume | Painting module (new dep) on existing storage |
| \*\*PDF engine\*\* | \*\*Playwright + headless Chromium\*\* | Painting module (new dep) — renders print view via print.css |
| AI draft | Claude SDK (structured output) | Painting module (new dep); skill rules as system prompt |
| AI image / web search | Pluggable, optional | Painting module — degrade gracefully without keys |
| Auth | Host app's existing session | \*\*STL-Inventory (existing)\*\* — single local user |

  

**Auth (v1):** reuse STL-Inventory's existing access model — it's a single-user local app, so the painting routes simply sit behind whatever the host app already does. No new auth system. Remote/multi-user is out of scope (Section 17).

  

## 14\. Deployment: STL-Inventory's existing setup

There is **no new deployment** to design. The module ships with STL-Inventory, which already supports two run modes:

  

  - **Standalone binary** (recommended for normal use): the single executable that auto-opens http://localhost:8484. The painting screens just appear as new sections.
  - **Docker Compose** (advanced): docker compose up --build, served via nginx on port 80.

### 14.1 What the module adds to the existing setup

  - **Backend deps:** add numpy, scikit-image, pillow, playwright (+ Chromium), and the Claude SDK to STL-Inventory's requirements. Chromium is the one heavyweight addition — it must be installed into the backend Docker image **and** bundled into the standalone-binary build (a packaging note for the release workflow, since PDF rendering needs it at runtime).
  - **DB:** painting tables are created in the existing SQLite DB on startup/upgrade (same mechanism STL-Inventory uses for its own schema). They land in the existing user-data folder and survive app updates, exactly like the model catalog.
  - **Storage:** reference images reuse the existing local image volume/folder. Generated **PDFs/exports** write to an exports/ folder under the app's data directory so Brent can grab them to upload to Patreon.
  - **Settings:** new fields on the existing Settings page — Claude API key, optional image/search keys, PaintRack CSV path, PDF defaults (page size, footer/stamp). Everything optional; the module runs as a manual tool with no keys set.

### 14.2 Secrets & API keys — bring-your-own, never shipped

**No API key is ever committed to the repo or baked into a build.** Every user (including Brent) supplies their own. There are two supply paths, because there are two run modes:

  

1.  **Settings page (primary, works everywhere).** The user pastes their key into Settings; it's stored in a local **secrets store in the app's user-data folder** — *not* in the model/guide tables. This is the only path that works for the **standalone binary** (which has no Docker .env), and it matches STL-Inventory's existing "configure in Settings" pattern.
2.  **.env** **(Docker/dev override).** For Docker users, an env var (e.g., ANTHROPIC\_API\_KEY=) can supply the key. We commit a **.env.example** with blank placeholders and keep real .env git-ignored — exactly how STL-Inventory already handles STL\_DRIVE\_1. If both are set, env wins (handy for dev).

  

Resolution order at runtime: **env var → Settings value → unset (feature disabled)**.

  

Handling rules (call these out for Code):

  

  - Key is **masked in the UI** (show sk-…••••, allow replace), **never logged**, and **never returned** by any API read endpoint.
  - The secrets store is **excluded from the shareable** **.db** **backup** — so a backup you hand to someone (or post) can't leak your key. (See Section 11.)
  - Public builds ship with **all keys empty**; AI/Patreon features are simply inactive until a user adds their own key.

### 14.3 Graceful degradation (unchanged philosophy)

With no Claude key, the module is a manual authoring tool (no AI draft). With no image/search keys, the reference fallback chain skips straight to the linked-model image / upload / URL options. PDF and color-match work fully offline with no keys at all.

### 14.4 Path to remote later

Same as STL-Inventory's own path: if either app ever goes remote, swap the local image/exports folders for object storage and put a reverse proxy + TLS in front. Out of scope for v1 (Section 17).

  

## 15\. Milestones / roadmap

A build order that front-loads the load-bearing core (Paint Shelf + structured guides) and reaches the **real deliverable — a downloadable PDF — by M3**. Because we're building inside STL-Inventory, the old "foundations" milestone shrinks to a wiring task. Public reader is explicitly *not* on this path (Section 16).

  

**M0 — Module wiring into STL-Inventory (½ sprint)** Add the painting/ backend package, create the painting tables in the existing SQLite DB, add the painting deps (NumPy/scikit-image/Pillow/Playwright/Claude SDK) to requirements + Docker image + binary build, add nav entries and route shells in the React app, extend the test suite. *Exit:* the running app shows empty "Guides" and "Paint Shelf" sections; CI green; backups include the new (empty) tables. **No greenfield scaffolding — just extension.**

  

**M1 — Paint Shelf core (1 sprint)** Paint/line/brand models, Paint Shelf table UI (reusing STL-Inventory's grid/filter patterns), PaintRack CSV import with diff, export, code-convention validation, color chips. *Exit:* the real inventory is in the DB, round-trips to CSV, and renders chips. **This is the foundation everything else stands on.**

  

**M2 — Guide model + rendering + print + model link + golden fixtures (1–2 sprints)** Structured guide model (incl. model\_id), React reader components emitting guide.css classes, data-driven Thinning Reference, the **print view** (all tabs expanded) using print.css, static-HTML export, the **model↔guide link** (FK, ModelLink component, "Create/View guide" on the model detail page, "has guide" badge), and the **importer with 3–5 golden round-trip fixtures** (Section 9.7) driving the rendering work. *Exit:* a hand-entered guide renders identically to a current HTML guide, **the golden fixtures round-trip clean** (schema complete + renderer faithful), the print view is complete, and guides link to/from their STL model.

  

**M3 — Authoring + validation + PDF (1–2 sprints)** Guide wizard, structured editor with inventory-backed swatch picker, validation panel, **Playwright PDF generation** (single + series bundle, reward stamping). *Exit:* Brent can author a guide entirely in the app, bad paints/codes are blocked, and **publish produces a downloadable PDF ready for Patreon.** ← *first end-to-end value.*

  

**M4 — AI draft + color match (2 sprints)** Generation service (Claude, structured output, skill rules as prompt), draft→edit flow, color-match studio (sampling, CIEDE2000, value mode, palette), reference-image fallback chain (linked-model image → render → assisted web search → AI-gen → upload). *Exit:* AI drafts a guide, Brent edits and ships a PDF; color match suggests owned paints.

  

**M5 — Full-corpus import + polish (1 sprint)** Run the importer across all 38 guides; work the import reports as an **inventory-gap pass** (unresolved paints) and a **validator-calibration pass** (tune false-positives against approved work, Section 9.7); print/PDF parity pass; accessibility/contrast pass; content-tone linter. *Exit:* the full archive is in the app as reviewed drafts, re-exportable as PDFs, and the validator runs clean over known-good guides.

  

**Later — public gallery (deferred, Section 16).** Only if/when wanted.

  

## 16\. Deferred: the public website

Not built in v1, but designed-for so it's a clean add later. By the time M2 ships, the **reader components and print view already exist inside the app** — making them public is mostly an exposure + hosting problem, not a build-from-scratch one. Building it later means: a read-only public route surface (sketched in Section 7.1), an SSG/prerender step for SEO + speed, hosting + TLS + a domain, reference-image licensing review, and the caregiver-message /about page — and a decision about whether the public reader rides on STL-Inventory or is a separate static publish target. None of it touches the schema or the authoring module. The PDF distribution path keeps working regardless.

  

## 17\. Open questions / risks

|  |  |  |
| :-: | :-: | :-: |
| \*\*\\\#\*\* | \*\*Item\*\* | \*\*Notes / proposed default\*\* |
| Q1 | Hosting/deploy target? | \*\*Resolved: ships inside STL-Inventory\*\* (standalone binary or Docker, Section 14). Remote deferred with the public reader (Section 16). |
| \*\*Q0\*\* | Should the painting module ship in STL-Inventory's \*public\* releases? | \*\*Resolved (2026-06-07): yes, as an opt-in, bring-your-own-key feature.\*\* Module-level "Enable Painting Guides" toggle (off by default in public builds) + per-guide generation checkboxes (Section 4.7); every AI/Patreon capability gated on the user's \*own\* API key (Section 14.2). No keys, paint-data paths, or Patreon branding ship in the repo or build. Strangers get the module inert until they opt in with their own credentials. |
| Q2 | Image-model & search-provider choice/budget? | Both pluggable and optional; AI features degrade gracefully without keys. Pick when we reach M4. |
| Q3 | Do we want full guide revision history, or is updated\\\_at + archive enough for v1? | \*Default:\* updated\\\_at + soft archive in v1; revisions later. |
| Q4 | PDF page setup — page size (US Letter vs A4), margins, cover page for bundles? | \*Default:\* US Letter, modest margins, optional cover for series bundles. Easy to tweak in print.css. |
| Q5 | Reward stamping — watermark, tier label, "Patreon exclusive" footer: which do you actually want on? | \*Default:\* footer note on, watermark off. Configurable per export (Section 9.4). |
| Q6 | Hex accuracy | Inventory hexes are approximate; color match is "suggest, confirm by eye." Acceptable for v1; could improve with sampled chart scans later. |
| Q7 | Does the skill's HTML-parse generation backend earn its keep, or go Claude-API-only? | \*Default:\* Claude-API-only for cleanliness; keep skill as chat tool. |
| Q8 | Reference-image licensing (only matters once public) | Store provenance/attribution now; review usage rights before any public publishing. Moot while output is private PDFs. |
| Q9 (wargaming) | Does the module add the wargaming-painting guide type, or stay figure-only? | \*\*Recommendation: figure-first; extend after evidence.\*\* The extension is fully designed (Section 6.6) — a guide\\\_type discriminator + a few JSON blocks + a renderer branch, no core disruption. v1 ships figure-only; import the 12 wargaming guides at M5 to see exactly what extra structure they need, then add it as a bounded change. Deferring costs nothing. |

  

## Appendix A — The GuideDraft JSON contract

The object the AI emits, the editor mutates, and every renderer consumes. Shown as annotated TypeScript; the backend defines it as Pydantic models (the source of truth) and generates the matching TS. IDs follow the host app convention; the AI emits placeholder string IDs that the backend reconciles to real paint IDs on save.

  

type Hex = string;            // "\#RRGGBB"

  

type ValuePct = number;       // 0..100, approximate L\*-derived

  

type TechniqueTag = "airbrush" | "brush" | "wash" | "finish" | "effects" | "filter";

  

interface Swatch {

  

  paint\_ref: string;          // paint code+line the AI chose; backend resolves -\> paint\_id

  

  value\_pct: ValuePct;

  

  role\_label: string;         // "mid-tone base", "final specular"

  

}

  

interface MixComponent { paint\_ref: string; parts: number; }

  

interface Step {

  

  title: string;

  

  technique\_tag: TechniqueTag;

  

  body: string;               // instructions, value intent woven in

  

  value\_intent: string;       // explicit: "should read \~85% value; push it"

  

  swatches: Swatch\[\];

  

  mix?: MixComponent\[\];       // present for mixes; ratio derived from parts

  

  ratio\_box?: string;         // human-readable ratio when not a paint mix

  

  tip?: string;               // .tip  (green ✦)

  

  warning?: string;           // .warning (red ⚠)

  

}

  

interface Phase { label: string; steps: Step\[\]; }

  

interface ValueMap { chips: { hex: Hex; value\_pct: ValuePct; zone\_label: string }\[\]; } // len 5

  

interface SkinMethod { key: "basic"|"pinkle"|"wash\_tinting"; title: string; recommended: boolean; steps: Step\[\]; }

  

interface SkinConfig {

  

  recommended: "basic"|"pinkle"|"wash\_tinting";

  

  anchor\_paint\_ref: string;   // validated against complexion\_band

  

  complexion\_band: "very\_fair"|"fair\_warm"|"medium\_tan"|"warm\_olive"|"brown\_warm"|"deep\_dark";

  

  freckling\_note?: string;

  

  methods: SkinMethod\[\];      // all three present; one flagged recommended

  

}

  

interface MetalsConfig {

  

  tmm: { approach: "gloss\_black\_1to6"|"standard\_small"; steps: Step\[\] };

  

  nmm?: { steps: Step\[\] };    // only when NMM sub-tab requested (ask first)

  

}

  

interface Tab {

  

  name: string;               // "Skin", "Armor", "Metals", "Cloak"…

  

  phases: Phase\[\];

  

  value\_map?: ValueMap;

  

  skin\_config?: SkinConfig;   // only on the Skin tab

  

  metals\_config?: MetalsConfig; // only on a Metals tab

  

  has\_expert\_subtab?: boolean;

  

}

  

interface ThinningConfig {

  

  airbrush\_rows: { technique: string; nozzle: string; ratio: string; behavior: string }\[\];

  

  brush\_rows?: { technique: string; ratio: string; behavior: string }\[\];

  

  thinning\_cards?: { title: string; body: string }\[\];

  

}

  

interface CharacterBrief { philosophy: string; light\_source: string; priority\_materials: string\[\]; }

  

interface Theme {

  

  bg: Hex; surface: Hex; surface2: Hex; surface3: Hex; border: Hex;

  

  text: Hex; text\_muted: Hex; text\_dim: Hex; accent: Hex; hero\_gradient: string;

  

}

  

interface ValidationFlag {

  

  rule\_id: string; severity: "warn"|"block"; message: string;

  

  location: string;           // json-path to the offending node

  

  suggestion?: string;

  

}

  

interface GuideDraft {

  

  // header

  

  title: string; slug: string; franchise: string;

  

  scale: "1:6"|"1:12"|"75mm"|"28mm"|"bust"|"other";

  

  category: string; series?: string; model\_ref?: string;  // -\> STL-Inventory model

  

  creator\_credit: { name: string; url?: string };         // manufacturer/sculptor, NOT Brent

  

  technique\_tags: string\[\];

  

  // blocks

  

  character\_brief: CharacterBrief;

  

  theme: Theme;

  

  thinning\_config: ThinningConfig;

  

  reference\_image\_ref?: string;

  

  // body

  

  tabs: Tab\[\];                // Thinning Reference is appended by the renderer, not authored here

  

  // filled by the validator, never by the AI

  

  validation\_flags: ValidationFlag\[\];

  

}

  

Notes for Code: the AI returns validation\_flags: \[\]; the backend runs the validator and repopulates it. paint\_ref (not paint\_id) is what the model emits — the resolver maps each to a real paint or raises a paint.exists block flag. The Thinning Reference tab is **not** in tabs; it's injected at render time from thinning\_config + the shared static content (Section 9.3), so the AI can't get its structure wrong.

  

## Appendix B — validation\_rules.yaml (shape + fixtures)

The rule data the validator loads. Structural rules carry a small code predicate; data rules (skin bands, highlight directions) are fully declarative.

  

version: 1

  

scale\_value\_spread\_min:        \# for value.range, by scale

  

  "28mm": 60

  

  "1:12": 50

  

  "1:6": 40

  

  "75mm": 40

  

  "bust": 40

  

skin\_bands:                    \# for skin.anchor\_band (block) + skin.highlight\_direction (warn)

  

  - band: deep\_dark

  

    anchor\_pro\_acryl: \["Dark Flesh 068"\]

  

    anchor\_fanatic: \["Mocca Skin","Onyx Skin","Obsidian Skin"\]

  

    highlight\_direction: warm\_golden        \# NOT pink/cream

  

    forbid\_highlight: \["pink","cream\_white\_full\_strength"\]

  

  - band: brown\_warm

  

    anchor\_pro\_acryl: \["Dark Warm Flesh S08"\]

  

    anchor\_fanatic: \["Quartz Skin","Dorado Skin","Amber Skin"\]

  

    highlight\_direction: warm\_golden

  

  - band: medium\_tan

  

    anchor\_pro\_acryl: \["Advanced Flesh Tone S17","Tan Flesh 024"\]

  

    highlight\_direction: warm\_peach

  

  \# … warm\_olive, fair\_warm, very\_fair …

  

white\_black\_rule:

  

  pure\_white\_hexes: \["\#FFFFFF","\#F8F8F8"\]   \# allowed only when role\_label contains "specular"

  

  pure\_black\_hexes: \["\#000000"\]             \# allowed only: lining, pupil, canonical-black material, primer

  

  shadow\_anchor\_required: "Payne's Grey"     \# Expert Acrylics; flag black used as a shadow base

  

glaze:

  

  transparent\_red\_suggest: "FW Crimson Ink" \# glaze.transparent\_red

  

structure:

  

  thinning\_ref\_must\_be\_last: true

  

  trouble\_grid\_card\_count\_even: true

  

  forbid\_legacy\_classes: \[".mix",".plus",".ratio",".result-row"\]

  

**Regression fixtures** (each is a tiny GuideDraft + the flags it must produce):

  

|  |  |  |
| :-: | :-: | :-: |
| \*\*Fixture\*\* | \*\*Input\*\* | \*\*Must emit\*\* |
| diana\\\_anchor\\\_too\\\_light | deep\\\_dark skin, anchor = Shadow Flesh 042 | skin.anchor\\\_band \*\*block\*\* |
| diana\\\_pink\\\_highlight | deep\\\_dark skin, highlight = pink/cream | skin.highlight\\\_direction warn |
| robin66\\\_green\\\_tights | tights swatch = green | (content) skin.anchor\\\_band n/a — caught by review note fixture |
| capamerica\\\_flat\\\_red\\\_boots | boots as graphic red, no satin/leather value anchor | value.range warn on that tab |
| pure\\\_white\\\_basecoat | white swatch, role "base" not "specular" | value.white\\\_black\\\_rule warn |
| thinning\\\_not\\\_last | Thinning Ref tab in middle | structure.thinning\\\_last \*\*block\*\* |

  

These fixtures live in the painting test suite (pytest, in-memory SQLite) and run in STL-Inventory's existing CI, so the painting rules are guarded alongside the host app's own tests.

  

  

*End of document. v1.0 = a painting-guide module inside STL-Inventory: authors guides (AI-drafted, human-edited), grounds every recipe in the Paint Shelf, links guides to the STL models they're printed from, and exports Patreon-ready PDFs. Reuses STL-Inventory's stack, SQLite DB, backup, packaging, and CI. Public reader designed-for but deferred. First open item: Q0 — keep this module out of STL-Inventory's public builds (feature flag or private branch). Ready to hand Sections 3, 6 & 7 (+ Appendices A/B) to Code, which already knows the STL-Inventory codebase. The 38-guide HTML importer (9.6) doubles as the schema's acceptance test, and the corpus itself (9.7) is the ground truth for the renderer, the AI's house style, and validator calibration.*

  