"""
Destination-path templates for the library reorganize feature (#323).

This grammar is deliberately **separate** from ``services/layout.py``. The two
look superficially alike but mean opposite things and must never be conflatable:

  * ``layout.py`` describes the *scan-root prefix* — the levels **above** the
    creator, where ``{creator}`` is the LAST token and the scanner owns
    everything below it.
  * This module describes a model's **full destination folder** — every level
    from the scan root down to the model, where ``{creator}`` is typically the
    FIRST token.

Reorganize grammar (levels separated by ``/``):

  ``{creator}``    the model's creator name
  ``{character}``  the model's character grouping
  ``{title}``      the model's title (falls back to its folder name)

A template must contain at least one token, every ``{...}`` token must be a
known field, and literal (non-token) path segments are allowed between tokens
(e.g. ``Models/{creator}/{character}``). A malformed template raises
``ReorganizeTemplateError`` so the router can return 4xx rather than letting an
f-string ``KeyError`` surface as a 500.
"""
import re

CREATOR = "creator"
CHARACTER = "character"
TITLE = "title"

DEFAULT_TEMPLATE = "{creator}/{character}/{title}"
_VALID_FIELDS = {CREATOR, CHARACTER, TITLE}
_TOKEN_RE = re.compile(r"\{(\w+)\}")


class ReorganizeTemplateError(ValueError):
    """Raised when a reorganize destination template is malformed."""


def parse_template(template: str | None) -> list[str]:
    """Validate a template and return its ordered, non-empty path segments.

    Each returned segment is a raw template chunk (e.g. ``"{creator}"`` or a
    literal like ``"Models"``); use :func:`render_segments` to substitute field
    values. Raises :class:`ReorganizeTemplateError` on malformed input. An
    empty/blank template falls back to :data:`DEFAULT_TEMPLATE`.
    """
    template = (template or "").strip().strip("/\\")
    if not template:
        template = DEFAULT_TEMPLATE

    segments: list[str] = []
    found_token = False
    for raw in re.split(r"[/\\]", template):
        seg = raw.strip()
        if not seg:
            continue
        # Validate any tokens embedded in the segment; reject unknown fields and
        # malformed braces. Literal text around/between tokens is allowed.
        for field in _TOKEN_RE.findall(seg):
            found_token = True
            if field.lower() not in _VALID_FIELDS:
                raise ReorganizeTemplateError(
                    f"Unknown template field {{{field}}} — use "
                    "{creator}, {character} or {title}"
                )
        # A stray unmatched brace is a malformed token, not a literal.
        if ("{" in _TOKEN_RE.sub("", seg)) or ("}" in _TOKEN_RE.sub("", seg)):
            raise ReorganizeTemplateError(
                f"Malformed template segment {seg!r} — unbalanced braces"
            )
        segments.append(seg)

    if not segments:
        raise ReorganizeTemplateError("Template is empty after parsing")
    if not found_token:
        raise ReorganizeTemplateError(
            "Template must reference at least one of {creator}, {character} or {title}"
        )
    return segments


def render_segments(segments: list[str], values: dict[str, str]) -> list[str]:
    """Substitute field values into parsed segments, returning rendered names.

    ``values`` supplies pre-sanitized, non-empty strings for each field. Tokens
    are replaced case-insensitively; literal text is preserved verbatim. Callers
    own per-segment sanitization of the result.
    """
    rendered: list[str] = []
    for seg in segments:
        def _sub(m: re.Match) -> str:
            return values[m.group(1).lower()]
        rendered.append(_TOKEN_RE.sub(_sub, seg))
    return rendered
