"""HTML/CSS/URL sanitization for imported guide content (#440).

Guide imports preserve authored inner HTML, raw blocks, a per-guide <style>
block, and credit links. The Guide Reader renders these through
``dangerouslySetInnerHTML`` and a raw ``<style>`` tag, so unsanitized import
content is a stored-XSS sink: the reader shares the localhost origin with the
API, so injected script could drive state-changing requests.

Sanitization runs at import time (authoritative, before persistence). The
frontend reader sanitizes again at render time as defense-in-depth and to cover
guides stored before this fix.

HTML is sanitized with nh3 (the maintained ammonia binding) against a strict
tag/attribute allowlist. Inline ``style`` is intentionally stripped from body
HTML — per-guide theming lives in ``head_style`` (CSS-sanitized separately),
and structured colored elements (swatches, value chips) are re-rendered by the
reader from parsed data, not raw HTML.
"""
from __future__ import annotations

import re
from typing import Optional

import nh3

# Formatting + structural tags real corpus guides use (inline prose) plus the
# block tags that appear in unmodelled raw_blocks (wargaming tier/batch cards).
ALLOWED_TAGS: set[str] = {
    # inline
    "a", "abbr", "b", "br", "code", "em", "i", "kbd", "mark", "s", "small",
    "span", "strong", "sub", "sup", "u",
    # block / structural
    "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol",
    "p", "pre", "ul",
    # tables (tier/trouble grids)
    "table", "tbody", "td", "th", "thead", "tr",
}

# `class` is allowed everywhere so raw_blocks keep the hooks the guide CSS
# targets. `style` is deliberately excluded (see module docstring).
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    # `rel` is omitted intentionally: it is managed by nh3's ``link_rel`` and
    # listing it here makes nh3 panic.
    "*": {"class"},
    "a": {"class", "href", "title", "target"},
    "abbr": {"class", "title"},
    "td": {"class", "colspan", "rowspan"},
    "th": {"class", "colspan", "rowspan"},
}

ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto"}

_LINK_REL = "noopener noreferrer nofollow"


def sanitize_html(html: Optional[str]) -> str:
    """Sanitize a fragment of authored guide HTML against the allowlist.

    Strips scripts, event-handler attributes, unsafe URL schemes, inline
    styles, and any tag/attribute outside the allowlist. Safe formatting
    (``strong``/``em``/approved links) is preserved.
    """
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel=_LINK_REL,
    )


def sanitize_url(url: Optional[str]) -> Optional[str]:
    """Allow only http/https/mailto links (e.g. creator-credit href).

    Returns ``None`` for missing, non-http(s)/mailto, or otherwise unsafe URLs
    (``javascript:``, ``data:``, protocol-relative, etc.).
    """
    if not url:
        return None
    candidate = url.strip()
    # Reject control chars/whitespace used to obfuscate schemes ("java\tscript:").
    if re.search(r"[\x00-\x20]", candidate):
        candidate = re.sub(r"[\x00-\x20]", "", candidate)
    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", candidate)
    if scheme_match:
        if scheme_match.group(1).lower() not in ALLOWED_URL_SCHEMES:
            return None
        return candidate
    # No scheme: relative or fragment link — allow but never protocol-relative.
    if candidate.startswith("//"):
        return None
    return candidate


# --- CSS (head_style) ------------------------------------------------------

# The <style> block is not HTML; nh3 can't sanitize it. A guide's theme CSS is
# kept (user chose to preserve theming, #440) but neutralized against the known
# CSS-side injection vectors. Regex-based and intentionally conservative: it
# removes rather than rewrites anything suspicious.
_CSS_DANGEROUS = (
    re.compile(r"@import[^;]*;?", re.I),               # remote stylesheet pull
    re.compile(r"expression\s*\([^)]*\)", re.I),       # legacy IE CSS expression
    re.compile(r"(javascript|vbscript)\s*:", re.I),    # script protocols
    re.compile(r"url\s*\(\s*['\"]?\s*(?:javascript|vbscript|data)\s*:[^)]*\)", re.I),
    re.compile(r"</?\s*style", re.I),                   # </style> breakout
    re.compile(r"<!--|-->"),                             # comment tricks
)


def sanitize_css(css: Optional[str]) -> str:
    """Neutralize a guide's ``head_style`` CSS before it is injected as a
    ``<style>`` tag. Strips tag breakouts, ``@import``, ``expression()``,
    script-protocol URLs, and embedded markup. Plain visual CSS is preserved.
    """
    if not css:
        return ""
    cleaned = css
    # Drop any angle brackets first — valid CSS never contains them, but they
    # are the basis of every <style>-tag-breakout payload.
    cleaned = cleaned.replace("<", "").replace(">", "")
    for pattern in _CSS_DANGEROUS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()
