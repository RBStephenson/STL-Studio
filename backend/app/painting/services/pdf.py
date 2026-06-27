"""PDF export: guide HTML -> Playwright/Chromium -> print-ready PDF (spec §9.4).

Single-guide only (series bundling, async-job caching and reward stamping are
deferred — see #320). The PDF reuses the exact static-HTML export the round-trip
importer consumes (`rendering.render_guide_html`), but with the four corpus
assets (guide.css / print.css / guide.js / skills-reference.js) **inlined** so
the document is fully self-contained — the corpus `painting-guides/assets/`
directory isn't shipped in the Docker image or the standalone binary, only the
copies bundled under this package's `data/assets/` are.

Rendering runs the guide through headless Chromium with print media emulated, so
the same `@media print` rules that drive the in-browser print view (#262) shape
the PDF. JS runs, so the skills tabs and thinning tables that skills-reference.js
injects at runtime appear in the output.
"""
from __future__ import annotations

import html as _htmllib
import io
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.painting.models import Guide, GuideSeries
from app.painting.services.rendering import (
    GUIDE_CSS_HREF,
    GUIDE_JS_SRC,
    PRINT_CSS_HREF,
    SKILLS_JS_SRC,
    render_guide_html,
)

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "data" / "assets"

# US Letter is the corpus default (spec Q4). The single-guide path predates the
# bundle and shipped "A4"; kept as-is for that endpoint, while the bundle and any
# stamped export default to Letter.
PAGE_FORMAT_LETTER = "Letter"
PAGE_FORMAT_A4 = "A4"

_DEFAULT_FOOTER_TEXT = "Patreon-exclusive — please don't redistribute"
_DEFAULT_WATERMARK_TEXT = "Patreon Exclusive"


@dataclass(frozen=True)
class StampConfig:
    """Per-export reward-stamping options (spec §4.6, Q5).

    Footer is on by default (the Patreon-exclusive credit line); the watermark is
    off by default and opt-in for higher-protection exports. An optional tier
    label is appended to the footer.
    """

    footer: bool = True
    footer_text: str = _DEFAULT_FOOTER_TEXT
    tier_label: str | None = None
    watermark: bool = False
    watermark_text: str = _DEFAULT_WATERMARK_TEXT

    @property
    def is_noop(self) -> bool:
        return not self.footer and not self.watermark


class ChromiumNotInstalledError(RuntimeError):
    """Raised when Playwright's Chromium browser isn't installed.

    In Docker/CI it's installed at build time; the standalone binary needs a
    one-time `playwright install chromium` on first use (PyInstaller can't bundle
    the browser). The router maps this to a 503 with remediation guidance.
    """


class EmptySeriesError(ValueError):
    """Raised when a series-bundle export has no published guides to render.

    The router maps this to a 404 — there's nothing to download.
    """


def _read_asset(name: str) -> str:
    return (_ASSETS_DIR / name).read_text(encoding="utf-8")


def _stamp_into_html(html: str, stamp: StampConfig) -> str:
    """Inject reward-stamping CSS + markup into a self-contained guide document.

    Stamping is done at the HTML/CSS layer (not as a post-render PDF overlay) so
    text rendering stays Chromium's job — `position: fixed` elements repeat on
    every printed page, giving a per-page footer/watermark for free.
    """
    if stamp.is_noop:
        return html

    css_rules: list[str] = []
    body_markup: list[str] = []

    if stamp.footer:
        footer_text = stamp.footer_text
        if stamp.tier_label:
            footer_text = f"{footer_text} · {stamp.tier_label}"
        css_rules.append(
            "  .pdf-stamp-footer {\n"
            "    position: fixed; bottom: 4mm; left: 0; right: 0;\n"
            "    text-align: center; font-size: 9px; color: #999 !important;\n"
            "    print-color-adjust: exact !important;\n"
            "    -webkit-print-color-adjust: exact !important;\n"
            "  }"
        )
        body_markup.append(
            f'<div class="pdf-stamp-footer">{_htmllib.escape(footer_text)}</div>'
        )

    if stamp.watermark:
        css_rules.append(
            "  .pdf-stamp-watermark {\n"
            "    position: fixed; top: 50%; left: 50%;\n"
            "    transform: translate(-50%, -50%) rotate(-45deg);\n"
            "    font-size: 72px; font-weight: 700; letter-spacing: 4px;\n"
            "    color: rgba(255, 255, 255, 0.08) !important;\n"
            "    pointer-events: none; z-index: 9999; white-space: nowrap;\n"
            "    print-color-adjust: exact !important;\n"
            "    -webkit-print-color-adjust: exact !important;\n"
            "  }"
        )
        body_markup.append(
            f'<div class="pdf-stamp-watermark">'
            f'{_htmllib.escape(stamp.watermark_text)}</div>'
        )

    style_block = (
        '<style media="print">\n@media print {\n'
        + "\n".join(css_rules)
        + "\n}\n</style>"
    )
    html = html.replace("</head>", f"  {style_block}\n</head>", 1)
    html = html.replace("</body>", "\n".join(body_markup) + "\n</body>", 1)
    return html


def render_guide_pdf_html(
    db: Session, guide: Guide, stamp: StampConfig | None = None
) -> str:
    """The static-HTML export with all four corpus assets inlined.

    Built by post-processing `render_guide_html` output: the emitted asset tags
    are deterministic (constructed from the rendering module's href constants),
    so we reconstruct each exact tag and swap it for an inline equivalent. This
    keeps `render_guide_html` byte-identical for the #261 round-trip while making
    the PDF source self-contained.
    """
    html = render_guide_html(db, guide)

    guide_css = _read_asset("guide.css")
    print_css = _read_asset("print.css")
    guide_js = _read_asset("guide.js")
    skills_js = _read_asset("skills-reference.js")

    replacements = {
        f'  <link rel="stylesheet" href="{GUIDE_CSS_HREF}">':
            f"  <style>\n{guide_css}\n  </style>",
        f'  <link rel="stylesheet" href="{PRINT_CSS_HREF}" media="print">':
            f'  <style media="print">\n{print_css}\n  </style>',
        f'<script src="{GUIDE_JS_SRC}"></script>':
            f"<script>\n{guide_js}\n</script>",
        f'<script src="{SKILLS_JS_SRC}"></script>':
            f"<script>\n{skills_js}\n</script>",
    }
    for tag, inline in replacements.items():
        if tag not in html:
            raise RuntimeError(f"expected asset tag not found in export HTML: {tag!r}")
        html = html.replace(tag, inline, 1)
    # Emit the structured theme as :root vars (#515). Injected right after <head>
    # so a guide's verbatim head_style (later in the head) still wins as the
    # escape hatch. The static guide.css is var-driven but ships no :root
    # defaults, so this is also what makes editor-themed guides (which carry a
    # `theme` but no head_style) render in colour in the PDF.
    html = html.replace("<head>", "<head>\n" + _theme_style_block(guide), 1)
    if stamp is not None:
        html = _stamp_into_html(html, stamp)
    return html


# Defaults mirror the in-app reader (`guide-reader.css`) so the PDF matches the
# on-screen guide when a theme is partial or absent.
_THEME_DEFAULTS: dict[str, str] = {
    "bg": "#1a1a1a",
    "surface": "#222222",
    "surface2": "#2a2a2a",
    "surface3": "#333333",
    "border": "#3a3a3a",
    "text": "#e8e8e8",
    "text_muted": "#aaaaaa",
    "text_dim": "#777777",
    "accent": "#c0a060",
}
_DEFAULT_HERO_GRADIENT = "linear-gradient(135deg, var(--surface2), var(--bg))"
# CSS var name per GuideTheme field (text_muted -> --text-muted, etc).
_THEME_VAR_NAMES = {k: "--" + k.replace("_", "-") for k in _THEME_DEFAULTS}


def _theme_style_block(guide: Guide) -> str:
    """A `<style>` defining :root theme vars from the guide's structured theme.

    Defaults fill any field the theme doesn't set, so the output is always a
    complete, working palette.
    """
    theme = guide.theme or {}
    lines = []
    for field, default in _THEME_DEFAULTS.items():
        value = theme.get(field) or default
        lines.append(f"    {_THEME_VAR_NAMES[field]}: {value};")
    hero = theme.get("hero_gradient") or _DEFAULT_HERO_GRADIENT
    lines.append(f"    --hero-gradient: {hero};")
    vars_block = "\n".join(lines)
    return (
        "  <style>\n"
        f"  :root {{\n{vars_block}\n  }}\n"
        "  .hero { background: var(--hero-gradient); }\n"
        "  </style>"
    )


_PDF_MARGIN = {"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"}


def _series_guides(db: Session, series: GuideSeries) -> list[Guide]:
    """Published guides in a series, in stable id order.

    Drafts and archived guides are excluded — a bundle is a shippable reward, so
    it only carries published content.
    """
    return (
        db.query(Guide)
        .filter(Guide.series_id == series.id, Guide.status == "published")
        .order_by(Guide.id)
        .all()
    )


def _cover_html(series: GuideSeries, guides: list[Guide]) -> str:
    """A minimal dark cover page listing the bundled guides (spec Q4)."""
    items = "\n".join(
        f"    <li>{_htmllib.escape(g.title)}</li>" for g in guides
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '  <meta charset="UTF-8">\n'
        f"  <title>{_htmllib.escape(series.display_name)}</title>\n"
        "  <style>\n"
        "    html, body { margin: 0; height: 100%; background: #1a1a1a;\n"
        "      color: #e8e8e8; font-family: system-ui, sans-serif;\n"
        "      print-color-adjust: exact; -webkit-print-color-adjust: exact; }\n"
        "    .cover { display: flex; flex-direction: column; justify-content: center;\n"
        "      min-height: 100vh; padding: 0 18mm; box-sizing: border-box; }\n"
        "    h1 { font-size: 42px; margin: 0 0 8px; }\n"
        "    .sub { color: #999; font-size: 14px; letter-spacing: 2px;\n"
        "      text-transform: uppercase; margin-bottom: 28px; }\n"
        "    ul { list-style: none; padding: 0; font-size: 18px; line-height: 1.8; }\n"
        "    li::before { content: '▸ '; color: #888; }\n"
        "  </style>\n</head>\n<body>\n"
        '  <div class="cover">\n'
        f"    <h1>{_htmllib.escape(series.display_name)}</h1>\n"
        '    <div class="sub">Painting Guide Series</div>\n'
        f"    <ul>\n{items}\n    </ul>\n"
        "  </div>\n</body>\n</html>"
    )


def _merge_pdfs(parts: list[bytes]) -> bytes:
    """Concatenate already-rendered PDF byte blobs into a single document."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for blob in parts:
        reader = PdfReader(io.BytesIO(blob))
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def render_guide_pdf(
    db: Session,
    guide: Guide,
    stamp: StampConfig | None = None,
    *,
    page_format: str = PAGE_FORMAT_A4,
) -> bytes:
    """Render a guide to a print-ready PDF via headless Chromium.

    Uses Playwright's async API (the FastAPI request handler runs on the event
    loop, so the sync API would error). Print media is emulated and backgrounds
    are printed so swatch chips / value maps / theme colors come out right.
    """
    html = render_guide_pdf_html(db, guide, stamp)
    return (await _render_html_blobs([html], page_format=page_format))[0]


async def render_series_pdf(
    db: Session,
    series: GuideSeries,
    stamp: StampConfig | None = None,
    *,
    cover: bool = True,
    page_format: str = PAGE_FORMAT_LETTER,
) -> bytes:
    """Render every published guide in a series into one bundled PDF (spec §9.4).

    An optional cover page is prepended. Each guide is rendered to its own PDF and
    the blobs are merged — concatenating the guide *documents* would collide on
    per-guide theme `<style>` vars and duplicated tab/DOM ids.
    """
    guides = _series_guides(db, series)
    if not guides:
        raise EmptySeriesError(f"Series '{series.slug}' has no published guides")

    htmls: list[str] = []
    if cover:
        htmls.append(_cover_html(series, guides))
    htmls.extend(render_guide_pdf_html(db, g, stamp) for g in guides)

    blobs = await _render_html_blobs(htmls, page_format=page_format)
    return _merge_pdfs(blobs)


async def _render_html_blobs(htmls: list[str], *, page_format: str) -> list[bytes]:
    """Render N self-contained HTML docs to PDF blobs, reusing one browser.

    A single Chromium launch is amortised across the whole batch — bundle exports
    would otherwise pay a cold launch per guide.
    """
    # Imported lazily: Playwright pulls in heavy native bits, and importing it is
    # pointless on code paths that never render a PDF (e.g. the test suite when
    # Chromium isn't installed).
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    blobs: list[bytes] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                for html in htmls:
                    page = await browser.new_page()
                    try:
                        await page.set_content(html, wait_until="networkidle")
                        await page.emulate_media(media="print")
                        blobs.append(
                            await page.pdf(
                                format=page_format,
                                print_background=True,
                                margin=_PDF_MARGIN,
                            )
                        )
                    finally:
                        await page.close()
            finally:
                await browser.close()
    except PlaywrightError as exc:
        # Launch fails this way when the browser binary is missing.
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            raise ChromiumNotInstalledError(str(exc)) from exc
        raise
    return blobs
