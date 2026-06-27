---
name: Series badge CSS and link structure rule
description: Series-badge styling is defined in guide.css. Use <a> tags for other series guides, <span class="active"> for the current guide only.
type: reference
---

## Series Badge CSS — in guide.css

The `.series-badge` (and `.trio-badge`) styling is fully defined in `guide.css` as of May 2026. **Do NOT write inline series-badge CSS in new guides.** The guide.css definition uses CSS variables and includes `<a>` tag styling.

## HTML Structure

- `<span class="active">FirstName</span>` — current guide's character (short first name only, no full title)
- `<a href="filename.html">FirstName</a>` — all other characters in the series, in cast order
- Include ALL characters that have guides; do not omit any

## What guide.css defines

```css
.series-badge, .trio-badge {
  display: inline-flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; justify-content: center;
}
.series-badge a, .trio-badge a { /* link styling with var(--border), var(--text-muted), hover transitions */ }
.series-badge span, .trio-badge span { /* inactive pill styling */ }
.series-badge span.active, .trio-badge span.active { /* accent color highlight */ }
```

## When inline override IS needed

Only if a specific guide requires the badge to be positioned differently (e.g., left-aligned instead of centered). Override the specific property inline — do not duplicate the full CSS block.

**Why:** guide.css was updated to fully define series-badge with CSS variables and `<a>` tag support, replacing the previous per-guide inline CSS requirement.
