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
  ``{scale}``      the scanner-detected scale tag
  ``{title}``      the model's title (falls back to its folder name)

A trailing ``?`` marks a token **optional** (``{scale?}``): when that field has
no real value of its own the token contributes nothing, instead of rendering a
sentinel (``_Unknown Scale``) and blocking the row as unclassifiable
(STUDIO-407). Without it ``{scale}`` is close to unusable in practice — most
models carry no scale auto-tag, so a template referencing it blocks most of a
library at once.

Two consequences, both deliberate:

  * A segment whose tokens ALL dropped is dropped entirely, literals included,
    so ``by-{scale?}`` disappears rather than leaving a bare ``by-`` directory.
    A segment retaining any other content survives, so ``{creator}-{scale?}``
    renders ``Abe3D-`` *here* — the caller's slugify pass then strips the
    dangling separator, so the folder that reaches disk is ``abe3d`` unless
    slugify is off. Rejecting mixed segments outright would also have killed
    the useful ``by-{scale?}`` case, so this is the deliberate trade.
  * A template of ONLY optional tokens is rejected: every model could render to
    the same path and collide with everything.

A template must contain at least one *required* token, every ``{...}`` token
must be a known field, and literal (non-token) path segments are allowed
between tokens (e.g. ``Models/{creator}/{character}``). A malformed template
raises ``ReorganizeTemplateError`` so the router can return 4xx rather than
letting an f-string ``KeyError`` surface as a 500.
"""
import re
from collections.abc import Iterable

CREATOR = "creator"
CHARACTER = "character"
SCALE = "scale"
TITLE = "title"

DEFAULT_TEMPLATE = "{creator}/{character}/{title}"
VALID_FIELDS = (CREATOR, CHARACTER, SCALE, TITLE)
_VALID_FIELDS = set(VALID_FIELDS)
# Group 2 is the optional marker: "{scale?}" -> ("scale", "?").
_TOKEN_RE = re.compile(r"\{(\w+)(\?)?\}")


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
    found_required = False
    for raw in re.split(r"[/\\]", template):
        seg = raw.strip()
        if not seg:
            continue
        # Validate any tokens embedded in the segment; reject unknown fields and
        # malformed braces. Literal text around/between tokens is allowed.
        for field, optional in segment_fields(seg, validate=False):
            found_token = True
            found_required = found_required or not optional
            if field not in _VALID_FIELDS:
                raise ReorganizeTemplateError(
                    f"Unknown template field {{{field}}} — use "
                    "{creator}, {character}, {scale} or {title}, "
                    "optionally suffixed with ? (e.g. {scale?})"
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
            "Template must reference at least one of {creator}, {character}, {scale} or {title}"
        )
    if not found_required:
        raise ReorganizeTemplateError(
            "Template must reference at least one required field — with every token "
            "optional, a model missing all of them would render to the bare scan root "
            "and collide with every other such model"
        )
    return segments


def segment_fields(segment: str, validate: bool = True) -> list[tuple[str, bool]]:
    """``(field name, is_optional)`` for every token in one parsed segment.

    The single place that answers "which fields does this segment reference?".
    Callers previously each did their own ``"{" + field + "}" in seg.lower()``
    substring test, which silently sees nothing in ``{creator?}`` — one of those
    decided where a brand-new creator folder gets placed, so the miss was not
    cosmetic (STUDIO-407).

    ``validate=False`` is for :func:`parse_template`, which reports an unknown
    field with its own message rather than dropping it.
    """
    found = [(f.lower(), bool(opt)) for f, opt in _TOKEN_RE.findall(segment)]
    if validate:
        found = [(f, opt) for f, opt in found if f in _VALID_FIELDS]
    return found


def render_segments(
    segments: list[str],
    values: dict[str, str],
    dropped_fields: Iterable[str] = (),
) -> list[str]:
    """Substitute field values into parsed segments, returning rendered names.

    ``values`` supplies pre-sanitized, non-empty strings for each field. Tokens
    are replaced case-insensitively; literal text is preserved verbatim. Callers
    own per-segment sanitization of the result.

    ``dropped_fields`` names the fields whose value fell back to a sentinel, so
    an OPTIONAL token referencing one renders as nothing (STUDIO-407). It has to
    be passed in rather than inferred: ``values`` always holds a non-empty
    string, since a missing field arrives here already substituted with its
    ``_Unknown ...`` sentinel, so there is nothing in ``values`` for this
    function to detect.

    The returned list is ALWAYS the same length as ``segments`` — a segment
    whose every token dropped comes back as ``""`` for the caller to skip.
    Callers zip the two lists together (to decide per-segment slugging), so
    returning a shorter list would silently misalign them. The caller must also
    skip an empty result BEFORE sanitizing: ``sanitize_segment("")`` falls back
    to ``"_"``, which would turn a dropped level into a literal ``_`` directory.
    """
    drop = {f.lower() for f in dropped_fields}
    rendered: list[str] = []
    for seg in segments:
        fields = segment_fields(seg)
        dropped = 0

        def _sub(m: re.Match) -> str:
            nonlocal dropped
            name = m.group(1).lower()
            if m.group(2) and name in drop:
                dropped += 1
                return ""
            return values[name]

        out = _TOKEN_RE.sub(_sub, seg)
        # Every token in this segment dropped, so the level itself is gone —
        # including any literal text that only made sense alongside them.
        if fields and dropped == len(fields):
            out = ""
        rendered.append(out)
    return rendered
