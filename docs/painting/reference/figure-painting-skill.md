---
name: figure-painting
description: "Generate interactive HTML painting guides for scale model figures (1:6, 1:12, 28mm, 75mm, busts, etc.). Produces step-by-step color recipes with visual swatches, mapped to the user's specific paint brands, with airbrush vs. brush technique tags, thinning ratios, and weathering/finishing advice. Use this skill whenever the user mentions: painting a figure or miniature, color recipes, paint schemes, highlighting or shading techniques, miniature painting, scale model painting, wargaming painting, figure kit, garage kit, color palette for a figure, or wants help choosing paints for a character/model. Also trigger when the user references specific paint lines (Pro Acryl, Citadel, Vallejo, Army Painter, Scale75, AK Interactive, etc.) in the context of painting models or figures. Even if they just say \"I'm working on a figure\" or \"what colors should I use for X\" — use this skill."
---

name: figure-painting
description: >
  Generate interactive HTML painting guides for scale model figures (1:6, 1:12, 28mm, 75mm, busts, etc.).
  Produces step-by-step color recipes with visual swatches, mapped to the user's specific paint brands,
  with airbrush vs. brush technique tags, thinning ratios, and weathering/finishing advice.
  Use this skill whenever the user mentions: painting a figure or miniature, color recipes, paint schemes,
  highlighting or shading techniques, miniature painting, scale model painting, wargaming painting,
  figure kit, garage kit, color palette for a figure, or wants help choosing paints for a character/model.
  Also trigger when the user references paint lines (Pro Acryl, Vallejo, Army Painter, etc.) in the
  context of painting models or figures.
---

# Figure Painting Guide Generator

You create interactive, visually rich HTML painting guides that a hobbyist can reference at their workbench. These are actionable recipe cards with exact paint names, mix ratios, color swatches, and technique-specific instructions — not generic advice docs.

---

## Order of Priority

When building a guide, consult files in this order:

1. **Memory files** (highest authority — user-specific data):
   - `paint-inventory.md` — what paints the user actually owns; never suggest outside this
   - `airbrush-thinning-rule.md` — nozzle size = paint fraction rule
   - `skin-painting-methods.md` — all three canonical skin methods + decision table
   - `paint-code-conventions.md` — validate every Pro Acryl code before writing a swatch
   - `series-badge-css-rule.md` — note: series-badge CSS now lives in guide.css
2. **This SKILL.md** — all guide generation rules, structure, paint lines, HTML patterns
3. **Template HTML** — starting point: `<painting-guides>/figure-guide-template.html`

Memory files override SKILL.md defaults where they conflict. SKILL.md overrides template defaults. Template provides the HTML skeleton.

---

## Execution Rules (Apply to Entire Session)

**No narration before writing.** When producing a guide, go straight to the Write tool. No recap, no plan summary, no announcement.

**Single write.** Produce the complete guide in one Write call. If the guide is large enough to risk hitting the output limit (7+ full tabs with Expert sub-tabs, expected >90KB), use exactly two consecutive calls: Write call 1 through approximately the midpoint tab (include valid closing `</body></html>` tags), then immediately an Edit call replacing those closing tags with the remaining tabs + closing tags. Zero text between the two calls.

**Minimal task tracking.** Create exactly one task item — "Generate [figure name] guide" — mark in_progress before writing, completed after saving.

**Post-write response: one sentence + file link.** Nothing more after saving.

---

## Core Philosophy: Value First

**Value (light/dark contrast) is king. Hue (color) is secondary.**

A figure with perfect color accuracy but flat values looks lifeless. A figure with slightly "wrong" colors but strong value structure looks compelling from across the room. Every recipe decision serves value first.

### What This Means in Practice

1. **Establish value range first.** Decide darkest dark and lightest light for each surface before choosing colors. Wider than feels comfortable.
2. **Map values before hues.** Think in greyscale first. Where are deepest shadows? Where does light strike hardest?
3. **Highlights go lighter than you think.** Final highlight at display scale should be close to pure white. Push it.
4. **Shadows go darker than you think.** Deep recesses can go nearly black even on brightly colored surfaces.
5. **Chromatic intensity is reduced at extremes.** Most saturated color lives in mid-tones. Highlights shift toward warm/cream; shadows shift toward cool/desaturated. Never add white to lighten or black to darken — that creates chalky highlights and muddy shadows.

### Value Intent in Every Step Card

Every step must make value intent explicit:
> "This highlight should read as approximately 80–85% value (near-white). If it looks too subtle at arm's length, it's not bright enough. Push it."

### The Greyscale Check

Always include in Airbrush or Brush Skills tab: photograph figure, desaturate in phone's editor. Should read clearly in greyscale — visible light source, form, depth. If flat, values are too compressed. Fix values before fixing color.

### Value Priority by Scale

- **28mm**: Extreme contrast. Deep black shadows, near-white highlights.
- **1:12**: High contrast. Push highlights and shadows hard.
- **1:6 / 75mm / Busts**: More nuanced transitions possible — still push further than feels natural.

### Paint Selection Through a Value Lens

When recommending paints, always note approximate value alongside the color name:
- "Coal Black 002 (~5% value) — your deepest shadow anchor"
- "Warm Flesh 073 (~55% value) — mid-tone, the true skin color"
- "Heavy Warm White S18 (~92% value) — final specular highlight"

This trains the painter to think about what the paint does to value, not just what color it is.

### The White and Black Rule

Never use pure white or pure black as general-purpose painting colors. These are reserved for specific, intentional roles only. Using them carelessly flattens surfaces, kills temperature, and makes paint jobs look unfinished rather than refined.

#### Highlight Hierarchy — Whites

Highlights should shift warm or cool depending on your light source temperature, not simply "get lighter." Pure Titanium White reads as visually loud and integrates poorly unless it's the absolute final dot.

- **Working highlight (broad highlight passes):** Use a tinted near-white appropriate to the light temperature:
  - *Warm light source:* Bright Ivory, Heavy Warm White S18, or a pale cream mix
  - *Cool/neutral light source:* A heavily thinned pale blue-grey (e.g., Payne's Grey + Titanium White at high ratio) or a cool off-white
- **Final specular highlight (single dot or thin edge line only):** Pure Titanium White or Carbon White — reserved for the hottest point of direct light contact. One small dot. No larger.
- **Exception:** Materials that are canonically flat white (e.g., white fabric, white armor panels) use a near-white mid-tone with a pure white specular — same hierarchy, compressed range.

#### Shadow Hierarchy — Blacks

Pure black in a shadow reads as a hole rather than a deep value. It has no temperature, no interest, and no relationship to the colors above it. Payne's Grey (Expert Acrylics) is the default shadow anchor — it's dark enough to read as black at arm's length but carries a cool blue-grey temperature that gives depth and integrates naturally with overlying color layers.

- **Shadow base / zenithal shadow anchor:** Payne's Grey (Expert Acrylics) — your working "black." Use this wherever you'd reflexively reach for black in a shadow.
- **Deepest occlusion recesses (contact points, deepest undercuts):** Carbon Black (Pro Acryl) or Coal Black 002 — only where light genuinely cannot reach. These are accent points, not base layers.
- **Pure black — permitted uses only:**
  - Ink lining and panel line separation
  - Pupil dots and eye detail
  - Materials that are canonically flat black (rubber, certain plastics, black leather with no sheen)
  - Priming (Primer Black as zenithal base — this is not a painting color)

#### In Practice — The Decision Tree

Before reaching for white or black, ask:

1. Is this a final specular dot or the absolute deepest recess? → White or Carbon Black permitted.
2. Is this a material that is canonically that color? → Permitted with the specular hierarchy still applied on top.
3. Am I just trying to lighten or darken something? → Stop. Use a tinted near-white or Payne's Grey instead.

---

## Paint Lines and Color Reference

### Pro Acryl (Primary Documented Range)

Pro Acryl is the range these guides are built around and the method shown in the primary tab — it is the default starting point and the most fully documented line here. But **color accuracy governs the final pick, not brand**: choose whatever paint in inventory best hits the target value and hue (see "Accuracy over brand loyalty" below). Include product code alongside every name.

**Complete Pro Acryl Standard Range (with codes):**

*Skin & Flesh:* Peach Flesh · Tan Flesh 024 · Shadow Flesh 042 · Warm Flesh 073 · Dark Warm Flesh S08 · Olive Flesh 041 · Advanced Flesh Tone S17 · Bright Shadow Flesh S41 · Dark Flesh 068 · Beige Red S05

*Neutrals & Whites:* Bold Titanium White 001 · Coal Black 002 · Heavy Warm White S18 · Heavy Titanium White S21 · Satin Black S39 · Dark Neutral Grey 044 · Bright Neutral Grey 045 · Dark Warm Grey 016 · Warm Grey 074 · Neutral Grey 075 · Bright Warm Grey 015 · Beige Grey 006 · Cool Grey 002 · Slate Grey 013 · Brown Grey S22 · Bright Brown Grey 021 · Grey Green 022 · Red Grey S12

*Browns & Ambers:* Mahogany 009 · Burnt Sienna 059 · Burnt Umber 018 · Dark Umber 019 · Light Umber 018 · Warm Brown S09 · Dark Golden Brown 062 · Golden Brown 017 · Green Brown 020 · Petroleum Brown S14 · Black Brown 040 · Drab Brown S40 · Dark Green Brown S25 · Dark Orange Brown S26 · Orange Brown S27 · Caramel Brown S28 · Khaki 061 · Ivory 023 · Bright Ivory 022 · Dark Ivory S07 · Bone S23

*Reds:* Bold Pyrrole Red 003 · Burnt Red 008 · Black Red 004 · Burgundy 069 · Dark Burgundy S15 · Dark Crimson S19 · Mahogany 009 · AMP-017 Red Orange · Orange Red S31 · Red Oxide S37

*Oranges & Yellows:* Orange 007 · NOVA Orange S45 · Burnt Orange 037 · Orange Oxide S38 · Warm Yellow 072 · Golden Yellow 006 · Yellow Ochre 038 · Bright Yellow Ochre S29 · Bismuth Yellow S36 · Pale Yellow 060 · Bright Pale Yellow S30

*Greens:* Green 004 · Bright Green S33 · Camo Green 020 · Dark Camo Green 036 · Dark Yellow Green S06 · Yellow Green 065 · Bright Yellow Green 039 · Faded Green 066 · Bright Pale Green 058 · Jade 021 · Bright Jade 067 · Dark Jade S01 · Dark Emerald S20 · Green Oxide S16 · Black Green 057

*Blues:* Blue 005 · AMP-005 Dark Navy Blue · Dark Blue 034 · Dark Grey Blue 014 · Faded Ultramarine 013 · Sky Blue 012 · Ultramarine S35 · Blue Black 056 · Grey Blue 055 · White Blue S04 · Bright Green Blue 009 · Payne's Grey S02

*Purples & Magentas:* Purple 010 · Dark Purple 035 · Royal Purple S03 · Dark Plum S11 · Plum 070 · Faded Plum 063 · Magenta 011 · Dark Magenta S10 · Dark Hot Pink S32 · Pink 071 · Pale Pink 043

*Metallics:* Silver 025 · Dark Silver 030 · Steel 010 · Bright Gold 031 · Rich Gold 028 · White Gold 029 · Bronze 032 · Light Bronze 026 · Copper 027 · Dark Bronze S24 · Magnesium S42 · Metallic Medium 033

*Transparents:* Transparent Blue 046 · Transparent Red 047 · Transparent Green 048 · Transparent Yellow 049 · Transparent Orange 050 · Transparent Purple 051 · Transparent Brown 052 · Transparent Black 053 · Transparent White 064

*Washes:* Black Wash 200 · Brown Wash 201 · Flesh Wash 202

*Fluorescents:* Fluorescent Red F01 · Fluorescent Orange F02 · Fluorescent Yellow F03 · Fluorescent Green F04 · Fluorescent Purple F05 · Fluorescent Pink F06

*Primers:* P-002 Black · P-003 White · P-005 Dark Neutral Gray · P-007 Dark Camo Green · P-011 Black Brown · Primer Taupe · Primer Red Oxide · Primer Dark Purple

**Pro Acryl Primer rules — CRITICAL:**
- **NEVER thin primer.** Thinning breaks down its purpose and turns it into paint.
- **Use undiluted at 30+ PSI with a 0.5mm nozzle.**
- Can be applied by brush undiluted; self-levels well.
- **P-002 Black** — standard black zenithal base; required for Turbo Dork and The Pinkle Method.
- **P-003 White** — full white prime; use when Speedpaint 2.0 will be used as designed. Avoid for warm skin tones zenithal'd from black.
- **P-029 Primer Taupe** — mid-value warm neutral; excellent zenithal mid-tone over black for warm-toned figures.
- **P-005 Dark Neutral Gray** — versatile mid-dark grey; best all-purpose zenithal for most figures.
- **P-019 Primer Red Oxide** — warm dark red-brown; ambient occlusion for warm metallic surfaces, leather, rust.
- **P-023 Primer Dark Purple** — deep cool pre-shade; cold OSL, magical subjects, blue-purple shadow palettes.
- **P-011 Black Brown** — softer zenithal black alternative for warm-palette figures; good for skin and organic surfaces.

### Pro Acryl Expert Acrylics — Heavy-Body Tube Paints

the user owns the **full Expert Acrylics line** (Series 1 + Series 2). Heavy-body artist-grade acrylics — distinct from the dropper-bottle range. Very pigment-dense, excellent for glazing and drybrushing.

**When to reach for Expert Acrylics:**
- Any brush-only recipe where the Pro Acryl airbrush workflow isn't being used
- Glazing and layering on skin, leather, organic textures
- Drybrushing — heavy-body paints hold extremely well on a nearly-dry brush

**Complete color list:**
*Series 1:* Titanium White · Carbon Black · Pyrrole Red · Permanent Green Light · Prussian Blue · Pyrrole Orange · Burnt Umber · Dioxazine Violet · Burnt Sienna · Sap Green · Nickel Azo Yellow · Sepia · Payne's Grey · Primary Cyan · Primary Magenta · Primary Yellow
*Series 2 additions:* Chrome Oxide Green · Red Oxide Tint · Phthalo Turquoise Light · Quinacridone Magenta · Arylide Yellow Deep · Alizarin Crimson Hue

**Thinning Expert Acrylics:** Start at 2:1 (paint:water) for base coats. Glaze: 1:3 to 1:5. Drybrushing: near-undiluted. Never apply straight from tube.

**Key strengths:**
- Burnt Umber + Burnt Sienna + Sepia — ideal triad for aged leather, wood, warm organic recesses
- Sap Green + Carbon Black — dark near-black green for military, foliage, dark textiles
- Chrome Oxide Green — earthy green drybrush highlight for olive/military surfaces
- Payne's Grey — cool neutral shadow mixer and glaze for metals and cool-toned skin
- Dioxazine Violet — deep transparent purple shadow glaze mixer

### Accuracy over brand loyalty — picking the right paint

**Color accuracy beats brand for ALL paints, not just metallics.** Pick whatever paint best hits the target value and hue from what is in inventory; no brand gets a default preference. The one exception is paints whose medium genuinely behaves differently — choose those for the behavior, not the brand:

- **Pro Acryl Expert Acrylics — special case:** preferred for brush work and glazing for its extended open time and blendability. This preference stays.
- **Transparents, color-shift (Turbo Dork), and Speedpaint 2.0** — chosen for their finish/medium behavior, not interchangeable by hue alone.

The list below is the ranges on hand and their practical roles — **NOT a quality ranking**:

- **Pro Acryl Standard** — airbrush- and dropper-ready; the most fully documented range here.
- **Pro Acryl Expert Acrylics** — brush/glazing special case (above).
- **Army Painter Warpaints Fanatic** — excellent range; use the Flexible Triad System for value-mapped triads.
- **Army Painter Speedpaint 2.0** — one-pass basecoat+shade, or a filter/glaze over a sealed surface.
- **Citadel** — the user owns **Agrax Earthshade and Nuln Oil only**. Do not suggest any other Citadel paint.
- **Vallejo Model/Game Color** — precise and thin; good for glazing.
- **Vallejo Metal Color (VMC)** — pre-thinned ultra-fine metallics; a strong practical pick for fine airbrush metal work, but no default edge over other metallics.
- **All other brands** — do not suggest unless the user explicitly asks.

**Paint specificity rule:** Never say "use a dark brown wash" or "a bright green from your inventory." Always name the exact paint and brand: "Pro Acryl Brown Wash 201" or "Army Painter Warpaints Fanatic Strong Tone." **Do not suggest paints not in paint-inventory.md.**

Always name the specific paint AND the brand in every swatch.

### Army Painter Warpaints Fanatic — Key Colors for Figures

The Fanatic line's **Flexible Triad System** organizes paints into value-mapped rows.

*Skin (Rose):* Moonstone Skin · Agate Skin · Barbarian Flesh · Ruby Skin · Opal Skin · Pearl Skin · Obsidian Skin · Onyx Skin · Mocca Skin · Amber Skin · Dorado Skin · Quartz Skin
*Skin (Warm):* Carnelian Skin · Tiger's Eye Skin · Topaz Skin · Jasper Skin · Tourmaline Skin · Leopard Stone Skin
*Shades/Washes:* Light Tone · Soft Tone · Strong Tone · Dark Tone · Sepia Tone · Blue Tone · Green Tone · Purple Tone · Red Tone · Dark Red Tone · Orange Tone · Rust Tone · Military Shade · Dark Skin Shade · Strong Skin Shade · Dark Blue Tone

### Army Painter Speedpaint 2.0 — Standard AND Filter Use

**Thinning:** Always use **Speedpaint Medium** (not water) when thinning Speedpaint 2.0.

**Use 1 — Standard (as designed):** Over white or grey primer, flows into recesses and builds basecoat + shade + depth in one pass. One-pass product — overworking while wet activates self-leveling agent and ruins the blend. Let it flow and leave it.

**Use 2 — Filter/Glaze over sealed acrylic:** Apply thinned Speedpaint 2.0 (1:3 Speedpaint:Speedpaint Medium) over a fully dried and sealed (matte or satin varnish) layer. Pools lightly in recesses, leaves a color-temperature shift on raised surfaces. Wipe back lightly with a slightly damp flat brush for control. **Do NOT apply over unsealed acrylics — will lift soft layers.**

Key filter applications:
- Warming skin with Peachy Flesh or Blood Red over sealed flesh
- Cooling metals with Magic Blue over sealed silver
- Adding age with Burnt Moss, Occultist Cloak, or Ancient Honey over sealed leather/wood/stone

### Army Painter Warpaints Fanatic — Washes and Shaders

Match wash to surface temperature. Light Tone and Soft Tone for skin warmth. Strong Tone for general shadow on browns and yellows. Dark Tone substitutes for Black Wash. Agrax Earthshade (Citadel) for warm organic recesses.

---

## Before You Start

### Do NOT Read Existing Guides

When creating a new guide, do not read any existing guide file for any reason. The template + this skill + memory files contain everything needed. Reading existing guides adds significant token cost with no benefit.

**Only files to read when building a new guide:**
- `figure-guide-template.html` — structure starting point
- Memory files when a specific rule needs checking
- `paint-inventory.md` — only for non-standard brands or gap checking (see inventory usage rules below)

### Guide Type Disambiguation — Ask First

**Before proceeding**, confirm the model type if it wasn't made explicit. the user has two painting guide skills — this one (display figures) and `wargaming-painting` (tabletop miniatures). The workflows are fundamentally different. Do not guess.

If the request doesn't clearly indicate a display figure (e.g. just "make me a guide for X" with no scale or context), ask:

> "Are you painting a **1:6 scale figure** (or similar display scale), or a **wargaming miniature** (28mm, 32mm, etc.)?"

If the answer is a display figure, ask for the scale before proceeding. If wargaming miniature, hand off to the `wargaming-painting` skill instead.

Do not infer from the subject name alone — many subjects (fantasy characters, Space Marines, etc.) could be either a 1:6 collector figure or a 28mm wargaming model.

### Gather Context — Always Ask, Never Assume

You need these things before writing. If not already known from project files or context, **ask the user — do not guess:**

1. **What figure?** Character, franchise, or subject
2. **What scale?** 1:6, 1:12, 75mm, 28mm, bust — affects technique recommendations
3. **Which paint lines?** (Already known from preferences: Pro Acryl primary, Army Painter secondary)
4. **Application methods?** Airbrush, brush, or both? Specific airbrushes and nozzle sizes? Skill level?
5. **What sections need recipes?** Skin, armor, clothing, weapons, base, metals, etc.
6. **Any specific challenges?** Blood effects, NMM, OSL, etc.
7. **Current progress?** What's already painted?
8. **Reference image?** Ask if the user has one before searching. If they do, analyze for skin tone, surface texture, value structure. If they don't have one, then perform web research.

If the user has a project file in `memory/projects/`, read it for current status.

### Research the Subject

Before writing recipes, research what the finished figure should look like. Do not rely solely on training knowledge.

- **Search for reference images:** film stills, promotional photos, concept art, box art. Look for natural/neutral light shots.
- **Research actual materials:** real leather, fabric, metal — study how they behave under light.
- **For historical figures:** search period photographs, uniform documentation.
- **For fictional characters:** cross-reference multiple sources; note which version you're targeting.
- **Color accuracy note:** Screen representations of pigment colors are unreliable. Aim for the *intended* material color, not the photographed color under specific lighting.

State your references clearly in the guide introduction.

### Paint Inventory Usage — CRITICAL

**Do NOT read paint-inventory.md proactively.** Standard Pro Acryl and Army Painter Fanatic/Speedpaint 2.0 colors are already in this SKILL.md — use those without opening the inventory file.

**Only read paint-inventory.md when:**
- Recommending a Turbo Dork, John Blanche, Villainy Ink, Vallejo, or FW Ink color
- Checking whether a specific less-common code (Signature Series, AMP) is in inventory
- Looking up a substitute for a missing paint

**Never suggest paints not in paint-inventory.md.** Validate paint codes against paint-code-conventions.md before writing any swatch.

---

## HTML Guide Format

### Structure

```
Hero Banner        → Figure name, scale, dark themed header
Paint Lines Bar    → Shows which brands are used
Character Brief    → Philosophy, light source, priority materials
Tabbed Sections    → One tab per major area of the figure
  Each tab:
    Section Header + Description
    Phase Labels (section separators)
    Step Cards (ordered sequence):
      - Step Number tag (Airbrush / Brush / Wash / Finish / Effects / Filter)
      - Step Title (h3)
      - Instructions + value intent explicit
      - Color Swatches: dot + name + code + brand + value %
      - Mix Ratios (ratio-box) where applicable
      - Tips (green .tip) for technique advice
      - Warnings (.warning) for common mistakes
Metals Tab         → TMM primary + optional NMM sub-tab
Airbrush Skills    → Specific to user's actual airbrushes
Brush Skills       → Only techniques used in this guide
Thinning Reference → Always the final tab
```

### Design Principles

**Dark theme always.** `#1a1a1a` background family. Reduces eye strain in controlled lighting; makes swatches pop.

**Color swatches are essential.** Every paint gets a visual swatch — 36px colored square. Approximate the actual paint color in hex. Look up the color if uncertain — do not guess. Use the Hues chart and Fanatic Triad poster from project files.

**Product codes on every paint.** Every swatch must include the product code (e.g., "Coal Black 002", "Dark Warm Flesh S08"). Validates against paint-code-conventions.md.

**Technique tags on every step.** Colored pill label on every `.step-number`:
- **Airbrush** (blue, `--tag-airbrush: #2266aa`)
- **Brush** (green, `--tag-brush: #226622`)
- **Wash** (brown, `--tag-wash: #884422`)
- **Finish** (grey, `--tag-finish: #555555`)
- **Effects** (pink, `--tag-effects: #882244`)
- **Filter** (teal, `--tag-filter: #446688`) — Speedpaint 2.0 filter and Transparent paint glazes

**Mix ratios are specific.** Not "add some orange" — "4:1 Bold Pyrrole Red 003 to Orange 007."

**Value % on every swatch.** The `swatch-value` field states approximate value and role: `~50% value — mid-tone base`.

**Tips and warnings in context.** Immediately after the step they relate to.

### CSS Strategy

**All structural/layout CSS lives in guide.css.** The per-guide `<style>` block contains ONLY:
- `:root` theme variables (`--bg`, `--surface`, `--surface2`, `--surface3`, `--border`, `--text`, `--text-muted`, `--text-dim`, `--accent`, `--tag-*`, `--tip-*`, `--warn-*`)
- `.hero` background gradient and border

**Never copy CSS blocks from template comments into the guide** — they are documentation, not code to duplicate. Override a guide.css rule inline only when a specific figure requires it.

**Series badge CSS** — now defined in guide.css. Use `<span class="active">FirstName</span>` for the current guide and `<a href="filename.html">Name</a>` for other series guides. No inline CSS needed.

### HTML Structure Standards

- **`:root` CSS vars** — `--surface`, `--surface2`, `--border`, `--text`, `--text-muted` always defined; colors matched to figure's theme
- **Hero** — `.category → h1 → .subtitle → .film-ref (.film-ref em) → .series-badge → .creator-credit`; no hero-badge, hero-meta, or lore-note inside hero
- **Creator credit** — figure's manufacturer or sculptor (Hot Toys, Mezco, Sideshow, etc.). NOT the user. Include social link if available.
- **Guide footer** — always constant: the author's YouTube handle/URL and Instagram handle/URL (configured per deployment). Never a placeholder.
- **Paint bar** — label reads "Paint Lines Used"; every brand used anywhere in guide gets a `.paint-pill`
- **Character Brief** — `.char-brief` block below paint bar, before tabs; painting philosophy, light source, priority materials
- **Tabs** — `.tab.tab-btn` + `.tab-content` pattern; `showTab(id, el)` JS (no localStorage); first tab active by default
- **Value Map** — grid of 5 value chips with hex swatches, % values, and zone labels; in every Skin tab and any material tab with complex value structure
- **Skin tab structure** — method recommendation block → three method cards (`.method-cards` grid, recommended card flagged `.recommended` + badge) → freckling note → Pro Acryl / Expert Acrylics sub-tabs → step-by-step
- **Swatch rows** — `.swatches` container with `.swatch` items. Each `.swatch`: `.swatch-dot` (color hex inline) + `.swatch-info` > `.swatch-name` (name + code) + `.swatch-brand` + `.swatch-value` (~% value + role). All CSS in guide.css.
- **Mix rows** — `.swatches` pattern for each paint in the mix, followed by `.ratio-box`. Do NOT use old `.mix / .plus / .ratio / .result-row` pattern.
- **Tips** — `.tip` (green, `✦ TIP:` prefix)
- **Warnings** — `.warning` (red, `⚠ NOTE:` prefix)
- **Phase labels** — `.phase-label` (small uppercase, muted color, section separators)
- **Sub-tabs** — `.sub-tabs / .sub-tab / .sub-tab.expert-tab / .sub-content`; `showSubTab(group, id, el)` JS function required (defined inline in guide, not in guide.js)
- **No dairy analogies** in thinning tables; column header = "Behavior" not "Consistency"
- **JS** — `showTab()` and `showSubTab()` only; no localStorage
- **Scripts** — load order: `window.GUIDE_THINNING` config block → `guide.js` → `skills-reference.js` → inline `showSubTab()` + back-to-top.
- **Nav** — `.guide-nav` with `← All Guides` link to `../../index.html`

### Scale-Specific Adjustments

- **1:6 / 75mm / Busts**: Smooth blending critical. Multiple thin coats non-negotiable. Airbrush preshading adds depth. Room for subtle color transitions.
- **1:12**: Slightly more forgiving on blending; still benefits from layering.
- **28-35mm**: Speed and contrast over smooth blending. Higher contrast reads better at arm's length. Drybrushing and washes do heavy lifting. Speedpaints effective.

### Thinning Reference Tab

**Fully built by `skills-reference.js` — do not author HTML for this tab.**

The `#thinning-ref` div is an empty placeholder. `skills-reference.js` injects the complete tab on page load: nozzle callout, airbrush table (static rows + figure-specific rows), brush table, and thinning cards (Flow Improver, Speedpaint 2.0, Transparent Red warning).

**Your only job:** populate `window.GUIDE_THINNING.airbrushRows` in the guide's config block with the figure-specific rows (base coat, skin highlight, etc.).

```js
window.GUIDE_THINNING = {
  airbrushRows: [
    { technique: 'Base coat (skin)', nozzle: '0.3mm', ratio: '1:3 to 1:4', behavior: 'Semi-transparent; builds in passes without obscuring zenithal.' },
    { technique: 'Skin highlight',   nozzle: '0.2mm', ratio: '1:4 to 1:5', behavior: 'Very thin; floats onto raised planes.' },
  ],
  brushRows:    [],  // optional extra brush rows
  thinningCards:[]   // optional extra cards
};
```

Static content provided automatically: primer row, zenithal rows, transparent/glaze row, freckling row, both Speedpaint 2.0 rows, full brush thinning table, Flow Improver card, Speedpaint 2.0 card, Transparent Red ⚠ card.

### Airbrush Skills Tab

Always include if the user airbrushes. Specific to user's actual airbrushes.

**Tip dry fix (canonical):** Dried paint on needle tip causes spitting and spattering. Fix: use a dry brush lightly dipped in airbrush cleaner or thinner to gently remove dried paint from the needle tip. Short, gentle strokes. **Do not dip the needle tip in water. Do not let the ferrule enter the airbrush cap.**

**Primer note (canonical):** Do NOT thin primer. Use undiluted at 30+ PSI with a 0.5mm nozzle.

**Static content injected automatically by `skills-reference.js` — do not author these:**
- Zenithal sequence (Black Prime + White Zenithal steps, including primer warning)
- Greyscale check tip (after PSI table, via `#ab-greyscale-anchor`)
- Tip Dry / Spattering card (prepended as first card in `.trouble-grid`)

**Per-guide content to author:**
1. Nozzle assignments table (task → nozzle → why)
2. PSI/distance reference grid (`.psi-table`) — static priming/zenithal rows are fine to include for completeness
3. Technique-specific sections (blood spatter, OSL, NMM gradient — only if used in this guide)
4. Three troubleshooting cards (Blowback, Uneven Coverage, Paint Too Thin) — Tip Dry is injected, so 3 per-guide cards → 4 total → even count ✓

**Anchor div placement (required):**
- `<div id="ab-zenithal-anchor"></div>` — place immediately after the Zenithal Sequence phase-label
- `<div id="ab-greyscale-anchor"></div>` — place immediately after the PSI table

### Brush Skills Tab

Always include. Only techniques actually used in this guide. No generic filler.

**Greyscale check tip is injected automatically by `skills-reference.js`** at the end of `#brush-skills` — do not author it.

---

## Metals: TMM and NMM

Every guide with metal surfaces includes a **Metals tab** with TMM as the primary content.

### True Metallic Metal (TMM) — Required

Value-first even for metallics: near-black in deep recesses, primary metallic in mid-tones, near-white on apex edges. Metallics read flat without this contrast.

**Scale determines the TMM approach:**

#### TMM — 1:6 Scale and Larger (Gloss Black Base Method)

At 1:6 scale, polished metal surfaces show alternating bands of light and dark as surface planes change angle relative to the light source. The gloss black base method exploits this naturally.

**Principle:** A gloss black base coat acts as the permanent shadow layer. Metallic paints are applied selectively — only where light would strike — as semi-transparent layers over the black. The black bleeds through in receding planes automatically.

**Steps:**
1. **Gloss Black base coat** *(Airbrush or Brush)* — apply a thin, even gloss black over the entire metal surface (Satin Black S39 + a drop of gloss medium, or dedicated gloss black lacquer). Not primer black — needs to be glossy to create a reflective ground.
2. **Map the light/dark bands** — study the reference. Metal planes that face the light source are light; planes that turn away stay dark. On curved or twisted surfaces (blades, armor edges) these bands alternate down the form.
3. **Apply mid-metallic as a semi-transparent layer** *(Airbrush or Brush)* — pick the metallic that best matches the target steel tone; VMC and Pro Acryl both qualify. *Airbrush:* **VMC 77.702 Duraluminium** thinned 1:1 with distilled water onto light-facing planes, multiple thin passes, then build up with **VMC 77.701 Aluminium** over the center of lit planes. *Brush:* **Steel 010** or **Silver 025** thinned 1:3 to 1:4. The gloss black handles shadow planes — do not paint those.
4. **Bright edge highlight** *(Airbrush or Brush)* — apex edges and specular peaks only; choose by the highlight tone you need. *Airbrush:* **VMC 77.707 Chrome** (reduce PSI slightly, feather carefully). *Brush:* **Magnesium S42** or **Silver 025 + Heavy Warm White S18**.
5. **Shadow deepening and recess work (optional)** — Two complementary approaches:
   - *(Airbrush — preferred for silver/steel metallics)* **FW Payne's Gray Ink** lightly airbrushed into shadow-facing planes and recesses. Thin minimally — already fluid and transparent. Its satin finish preserves metallic reflectivity where washes would dull it. Not ideal for warm metallics (gold, copper).
   - *(Brush)* **Black Wash 200 or Nuln Oil** into deep mechanical recesses only (bolts, seams, grooves) where maximum contrast is needed. The gloss black base already handles broad shadow zones — use sparingly.
6. **Colored metallics (Gold, Bronze, Copper)** *(Airbrush or Brush)* — same gloss black base, then apply the colored metallic over light planes only; pick by hue match. *Airbrush:* **VMC 77.725 Gold**, **VMC 77.710 Copper**, or **VMC 77.704 Pale Burnt Metal** for bronze/heat tones. *Brush:* **Rich Gold 028**, **Bronze 032**, **Copper 027**. Shadow warm metals with a glaze of Transparent Brown 052 or Burnt Umber (Expert Acrylics) in recesses *(Brush)*.

**Key insight:** You are NOT covering the figure in metal paint. You are painting the *light* that hits the metal, leaving the black base to be the shadow. Restraint reads more convincingly than full coverage.

#### TMM — 28mm / 1:12 and Smaller (Standard Method)

1. Dark metallic base (Dark Silver 030 or Coal Black 002 + metallic)
2. Mid-metallic zenithal (Steel 010 or Silver 025)
3. Bright edge highlight (Magnesium S42, or Silver 025 + Heavy Warm White S18)
4. Targeted recess wash (Black Wash 200, Nuln Oil, or Strong Tone)
5. Colored metallics (Gold, Bronze, Copper) follow same pattern with appropriate shadow/highlight mix

### Non-Metallic Metal (NMM) — Optional Sub-Tab

Add an NMM sub-tab when NMM is appropriate for the figure (display pieces, stylized/artistic looks, requests from the user). Use the sub-tab pattern: TMM primary, NMM as `<div class="sub-tab">` sibling.

**When to add NMM:** Ask the user. Do not assume.

**NMM approach:**
- No metallic paint. Illusion created by extreme value contrast + smooth gradient.
- Near-black in recesses, smooth grey gradient up, near-white on apex edges.
- The harder/more abrupt the transition, the shinier the metal reads.
- Cold steel: neutral white highlights. Warm gold: warm cream highlights.

---

## Skin Tone Methods

For every figure with paintable skin, read `skin-painting-methods.md` from memory for the full canonical content: all three methods (Basic, Pinkle, Wash Tinting), freckling, mid-tone reference table, and decision table. Use the decision table to pick the single most appropriate method for the character, and present only that method in the Skin tab — led by a brief character analysis justifying the choice. The other methods are reference for choosing, not content to reproduce in every guide.

**Quick decision reference:**
- Fair/feminine/heroic display → Method 2A (Pinkle)
- Rugged/masculine/weathered → Method 2B (Red Zenithal)
- Maximum realism, time to invest → Method 3 (Wash Tinting — uses Speedpaint Medium for filter variant)
- 28mm, cartoon, anime, first-time painter → Method 1 (Basic)

---

## Varnish and Finish Guidance

- **Matte**: Fabric, felt, rubber, matte plastics
- **Satin**: Leather, skin, slightly worn surfaces (mix matte + gloss ~2:1)
- **Gloss**: Wet blood, fresh wounds, polished metal, patent leather, eyes (targeted gloss only)

Contrast between finish types is what makes a figure look realistic.

---

## Transparent Resin Tinting

When a guide involves a clear/transparent resin part (weapon, prop, OSL element):
- **Thin Speedpaint 2.0 with Speedpaint Medium (1:3 Speedpaint:Speedpaint Medium), apply over matte-sealed surface.** Multiple thin passes rather than one heavy pass.
- **Do NOT recommend alcohol inks** — the user does not own them.
- **Do NOT recommend UV resin casting** — if the part is transparent resin, it is already printed. The workflow is tinting an existing print.
- Matte seal step before Speedpaint tinting is required — bare resin resists water-based paint.
- Gold or metallic hardware accents go on top of tinted resin as brush-only details.
- Finish with gloss varnish — amplifies translucency.

---

## The HTML Template

**Starting point for every new guide (MANDATORY):** Read the template file:
`<painting-guides>/figure-guide-template.html`

This is a lean skeleton with placeholders. It already encodes the current gold standard structure. **Do NOT read any existing guide file (Cassie, Superman, RoboCop, or any other) for structural reference.** The template + this skill + memory files contain everything needed.

**For updates to existing guides:** Small targeted fixes (one step, one paint, one warning) → use Edit tool with a precise string match, do NOT read the full file. Substantial changes (new tab, structural overhaul) → start fresh from the template.

Key things to customize per figure:
- Hero title, subtitle, category label, theme colors
- Creator credit — figure's manufacturer/sculptor (NOT the user)
- Guide footer — always constant (author's YouTube + Instagram handles)
- Paint lines bar — every brand used anywhere
- Series badge — `<span class="active">` for this guide, `<a>` tags for other series guides
- Tab names and count (match the figure's distinct areas)
- Step content, swatches, mix ratios, value % on every swatch
- Add Metals tab with TMM; add NMM sub-tab if appropriate (ask first)
- Airbrush Skills: specific to user's actual airbrush models and nozzle sizes
- Brush Skills: only techniques used in this guide
- Thinning reference specifics for the paint lines being used

### Expert Acrylics Sub-Tab Pattern

Every tab that has a meaningful Expert Acrylics brush-only alternative **must include a Pro Acryl / Expert Acrylics sub-tab pair.** Purple accent color (`#8855cc` family) to visually distinguish.

**Include for:** Skin, organic surfaces, leather, fabric, wood, bases.
**Skip for:** Metallics, thinning ref, skills tabs.

Sub-tab HTML structure and `showSubTab()` JS are in the template — copy from there.

---

## Color Accuracy Checker — Required Before Writing Any Recipe
Before committing any color recipe to a guide, run this checklist. Wrong
paint choices send a painter in the wrong direction from step one. Catching
errors here is far cheaper than correcting a painted figure.

This applies to every material, but skin tone is the highest-risk area.

---

### Step 1 — Establish Ground Truth
Before writing a single paint name:
1. Research the character's canonical appearance. Search for film stills,
   screencaps, promotional art, concept art, or box art. Prefer neutral or
   natural-light references — production lighting and render lighting distort
   true surface color.
2. Name the skin tone explicitly. Not "dark skin" — "rich deep brown, warm
   undertone, approximately 30–35% value at mid-tone."
3. State which reference you're using. If sources conflict, note it and ask
   the user which version to target.
4. Do not rely on sculpt render previews. Render lighting inflates highlights
   and deepens shadows. The surface color will appear lighter or darker than
   the canonical character.

---

### Step 2 — Skin Tone Anchor Validation
The anchor paint is the mid-tone that establishes the character's true skin
color. Validate it against this table before proceeding. Both Pro Acryl and
Army Painter Fanatic triads are listed — use whichever brand you're working
with. AP triads are listed highlight · mid-tone · shadow.

| Complexion band         | Pro Acryl anchor                        | Army Painter Fanatic triad (hi · mid · shadow)                    |
|-------------------------|-----------------------------------------|-------------------------------------------------------------------|
| Very fair / porcelain   | Shadow Flesh 042 / Bright Shadow Flesh S41 | Pearl Skin · Opal Skin · Ruby Skin (Rose 1)                    |
| Fair / warm             | Warm Flesh 073 / Peach Flesh        | Barbarian Flesh · Agate Skin · Moonstone Skin (Rose 2)            |
| Medium / tan            | Advanced Flesh Tone S17 / Tan Flesh 024 | Leopard Stone Skin · Tourmaline Skin · Jasper Skin (Warm 1)       |
| Warm olive / Mediterranean | Olive Flesh 041                      | Topaz Skin · Tiger's Eye Skin · Carnelian Skin (Warm 2)           |
| Brown / warm dark       | Dark Warm Flesh S08                     | Quartz Skin · Dorado Skin · Amber Skin (Deep 1)                   |
| Deep / dark brown       | Dark Flesh 068                          | Mocca Skin · Onyx Skin · Obsidian Skin (Deep 2)                   |

If the anchor is lighter than the character's complexion band, flag it
immediately. This is the most common error. Using Shadow Flesh 042 as the
anchor for a character with deep brown skin (e.g. Diana the Acrobat)
produces a light caramel result regardless of how the pinkle or shadows are
layered beneath it. Shadow Flesh is a highlight or raised-plane accent for
dark complexions — not an anchor. The same applies to AP: Pearl Skin and
Opal Skin are Rose triad 1 — they are very fair anchors and highlights only.

---

### Step 3 — Highlight Direction Validation
Highlight paint choices must shift in the correct direction for the skin tone:

  Fair skin:      shift warm pink-cream toward near-white
                  PA: Bright Shadow Flesh S41, Heavy Warm White S18
                  AP: Pearl Skin; mix with MPA-001 for specular peaks
  Medium/tan:     shift warm peachy-cream
                  PA: Advanced Flesh Tone S17 + Bright Shadow Flesh S41
                  AP: Leopard Stone Skin on upper planes
  Dark brown:     shift warm golden-amber
                  PA: Advanced Flesh Tone S17 — NOT pink or cream tones
                  AP: Quartz Skin — warm golden; avoid Rose triad paints
  Deep dark:      shift warm golden ONLY
                  PA: no pink or cream-white highlight paints at full strength —
                  these read chalky or tonally wrong on deep complexions
                  AP: Mocca Skin — warm coffee highlight; no pink or pearl tones

---

### Step 4 — The Arm's Length Read
Before finalizing any recipe, ask: if a painter follows these steps exactly
and photographs the figure from arm's length, will it look like the canonical
character?

Failure modes to check:
- Mid-tone anchor too light for the character's complexion
- Highlight direction wrong for the skin tone (pink on dark skin, cool on warm)
- Value range too compressed — shadow and highlight too close in value
- Material confusion — a color correct for one material (tan leather) being
  used for another (skin) and producing a confused read

---

### Step 5 — Flag Errors Explicitly
If you catch a problem, say so before proceeding. Do not silently correct it.
Do not bury the note in a tip callout. Use this format:

  ⚠ COLOR ACCURACY FLAG: [paint name] sits at approximately [value]% —
  this is consistent with [wrong complexion band], not [character's actual
  complexion]. For [character name], [correct paint] is the appropriate
  anchor. Substituting now.

Then proceed with the corrected recipe. This is quality control. the user has
explicitly requested that wrong premises be caught before they reach paint.

---

### Known Failure Cases — Do Not Repeat
| Figure              | Error                                              | Correct approach                                              |
|---------------------|----------------------------------------------------|---------------------------------------------------------------|
| Diana the Acrobat   | Shadow Flesh 042 used as mid-tone anchor           | Dark Flesh 068 as anchor; Shadow Flesh only as raised-plane accent |
| Diana the Acrobat   | Highlight shifted pink-cream instead of warm-golden | Advanced Flesh Tone S17 for highlights; no pink/cream on deep skin |
| Robin (1966)        | Tights painted green                               | Tights are nude/flesh-colored; green shorts are a separate garment |
| Captain America     | Boots treated as flat graphic red                  | Boots are red leather — distinct satin finish, darker value anchor |

Add a row to this table whenever a new error is caught and corrected.

---

## Accuracy Validation (Required Before Output)

Confirm before writing the guide:
- Matching HTML structure and layout to template
- Correct section placement (no quotes in tabs; quote only in hero .film-ref)
- Consistent UI patterns (swatch rows, ratio-box, not old .mix/.plus/.ratio patterns)
- No empty or placeholder tabs
- No duplicated content
- Every paint code cross-checked against paint-code-conventions.md
- Every paint confirmed in paint-inventory.md
- Trouble-grid has even number of cards
- Thinning ref is the last tab

---

## Consistency Enforcement

- All guides follow: Hero/Header → Paint Bar → Character Brief → Tabs → Skills → Thinning Ref
- Do NOT create new layouts or UI patterns
- **Consistency (layout) > optimization > creativity** (structure only, not painting decisions)
- Painting content may improve (with validation)

---

## Clarification Rules — Ask, Never Assume

When uncertain about **anything**, ask. Do not guess or proceed based on assumption:
- Colors, paint choices, structure, references, section relevance
- Whether NMM is appropriate for the figure
- Which skin method fits the character
- Any unclear instruction or ambiguous requirement

If references conflict → ask which to prioritize.
If "when appropriate" is unclear → ask.
Do NOT invent lore, quotes, or details not confirmed by research.
Mark unknowns as **Needs Confirmation**.

---

## Language & Tone

- Clear, supportive, and inclusive
- Do NOT use: "no skill required", "anyone can do this", "easy", "super easy"
- Avoid minimizing the learning process
- Encourage growth and practice
- Be direct, honest, respectful

---

## Saving and Presenting

### Step 1 — Determine the category folder

Map the figure's franchise/source to the correct subfolder:

| Franchise type | Folder |
|---|---|
| Live-action films, TV shows | `film-tv` |
| Comic book characters | `comics` |
| D&D Animated Series characters | `dnd-animated-series` |
| Anime, vocaloids, music-themed figures | `anime-music` |
| Wargaming figures (Warhammer 40k, Age of Sigmar, tabletop RPG minis) | `wargaming` |

**If the figure does not fit any category above:** Create a new subfolder with a descriptive kebab-case name (e.g., `horror-figures`, `video-games`, `historical`). Update `index.html` to add the new `div.cat` block for the new category. Do not default to `film-tv` if the figure does not belong there.

### Step 2 — Construct the save path automatically

```
Base:     <painting-guides>/
Category: by-category\[folder]\
Filename: [kebab-case-character-name]-painting-guide.html
```

Never ask the user for the path — derive it from the character name and category.

### Step 3 — Save the reference image

Every guide gets a reference image thumbnail in the hero section. Source and save it before writing the guide.

**Image source priority:**
1. **User-supplied image** — if the user provides one, use it directly
2. **Web search** — search for the character name + figure/kit manufacturer (e.g. "Hot Toys RoboCop 1987"). Prefer official product photos, film stills, or high-quality promo art. Download/save the best result.

**Save location:**
```
<painting-guides>/by-category/[folder]/img/[character-name]-reference.jpg
```
Create the `img/` subfolder if it doesn't exist. The guide's `src="img/[character-name]-reference.jpg"` path is relative and resolves correctly from the guide's location.

**In the guide HTML:** The template `.ref-thumb-wrap` block is already wired up. Update:
- `src="img/[character-name]-reference.jpg"` — the image filename you saved
- `alt="[Character Name] — reference"` — used as the modal caption

If no suitable image can be found or downloaded, omit the entire `.ref-thumb-wrap` block from the guide.

### Step 4 — Save the guide file

Write to the full constructed path. If a file already exists, overwrite it in place. Do not create versioned backups, do not ask for confirmation, do not read the existing file.

### Step 5 — Update index.html (ALWAYS — do not skip)

Index: `<painting-guides>/index.html`

Add card to the correct `div.cat` section:
```html
<div class="card"><a href="by-category/[folder]/[filename].html">[Display Name]</a><div class="meta"><span class="tag">1:6</span> [2-4 word descriptor · key material · notable technique]</div></div>
```

If the category is new, add a new `div.cat` block. Match the style of existing blocks.

### Step 6 — Present the file link

Provide a `computer://` link to the saved guide. One sentence confirming what was saved. Nothing more.