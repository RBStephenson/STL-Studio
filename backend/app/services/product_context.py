"""Pure product/package context shared by scan-time grouping consumers.

The scanner's ``character`` value is hierarchy-derived: it represents the
product envelope selected while walking a creator tree.  Reorganize uses the
same concept when it separates a character envelope from its release packages.
This module turns that durable scan result into a small, side-effect-free value
object so grouping can use hierarchy without depending on either workflow.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services import name_parser


@dataclass(frozen=True)
class ProductContext:
    """Hierarchy-derived product identity for one indexed model."""

    product_key: str | None
    display_label: str | None


def resolve_product_context(
    *, folder_path: str, character: str | None, creator_name: str | None
) -> ProductContext:
    """Resolve hierarchy identity without reading the database or filesystem.

    ``folder_path`` is accepted deliberately even though the initial resolver
    only needs the scanner-assigned character.  It keeps the contract ready for
    richer package-boundary evidence without coupling callers to ``Model``.
    """
    del folder_path
    if not character or name_parser.is_structural_folder(character):
        return ProductContext(product_key=None, display_label=None)
    key = name_parser.character_key(character, creator_name).strip().casefold()
    if not key:
        return ProductContext(product_key=None, display_label=None)
    return ProductContext(
        product_key=key,
        display_label=name_parser.display_name(character, creator_name),
    )
