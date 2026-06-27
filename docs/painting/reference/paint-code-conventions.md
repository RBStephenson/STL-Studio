---
name: Pro Acryl paint code conventions
description: Canonical name+code mapping rules for Pro Acryl Standard / Signature / AMP / Transparent / Wash / Primer / Texture lines. Use to validate any swatch reference in a painting guide.
type: reference
---
**Source charts:** Pro Acryl Set List · Hues chart · Naming chart (codes 001–075, S01–S49, AMP); Speedpaint 2.0 Practical Naming Chart; Warpaints Fanatic Practical Colour Name Chart, Conversion Chart, Flexible Triad System.

**Canonical Pro Acryl conventions to follow when writing guides:**

1. **Standard line:** 3-digit codes 001–075. Examples: 001 Bold Titanium White · 002 Coal Black · 005 Blue · **008 Burnt Red** (NOT Peach Flesh — Peach Flesh is a Signature/AMP S-code) · 018 **Light** Umber · 019 **Dark** Umber · 022 Bright Ivory · 023 Ivory · 054 **Turquoise** · 064 **Transparent White**.
2. **Signature line:** S-prefix S01–S49. Examples: S04 White Blue · S13 Dark Sea **Ben** (named after Ben Komets — *not* "Den") · S22 Brown Grey · S35 Ultramarine.
3. **AMP line:** Reuses 3-digit codes that overlap Standard codes but with different paints. Disambiguate with "AMP" in the name. Examples: AMP 002 Cool Grey · AMP 004 Black Red · **AMP 005 Dark Navy Blue** (NOT S25 — S25 is Dark Green Brown) · AMP 010 Steel · AMP 013 Slate Grey · AMP 017 Red Orange · AMP 018 Burnt Umber.
4. **Metallics:** 025–033 (no M-prefix). 025 Silver · 028 Rich Gold · **029 White Gold** (no "White Cold" exists) · **030 Dark Silver** (not "M26" or any M-prefix) · 031 Bright Gold · 032 Bronze · 033 Metallic Medium.
5. **Transparents:** 046–053, **064**. Transparent White is **064**, not 054. (054 is Turquoise.)
6. **Washes:** 200 Black · 201 Brown · 202 Flesh.
7. **Primers:** **P-002 Black, P-003 White**, P-005 Dark Neutral Grey, P-007 Dark Camo Green, P-011 Black Brown. (No P-001.)
8. **Textures:** T01–T08.
9. **Fluorescents:** F01–F06.

**Why:** During a 2026-05-02 audit, several guides had paints invented or miscoded — Transparent White as 054 instead of 064, Dark Silver as "M26", White Gold as "White Cold M29", Dark Navy Blue tagged as Signature S25 when it's AMP 005, etc. All such fabrications must be cross-checked against the source charts before writing a swatch.

**How to apply:** When writing or auditing any painting guide, every `<paint name> <code>` reference must match one of the rows above. For ambiguous shared codes (002, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 017, 018, 020, 021, 022, 023, 024) the paint NAME is what disambiguates Standard vs AMP — so the name must spell exactly what the source chart lists for that line.

> In the app, the **Paint Shelf** (with per-line code patterns) is the live source of truth for which paints exist and how codes are formatted; this file documents the naming conventions behind those rules.
