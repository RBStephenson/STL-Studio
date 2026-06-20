"""PaintRack CSV import (with diff preview) and export (#242/#243).

Format (observed from real PaintRack exports):
    Brand,SKU,Paint Name,Paint Class,Size,Count

Real-world quirks this module must handle:
  - Paint Class is often EMPTY (Pro Acryl's base MPA line, Dirty Down).
    The class string maps verbatim to PaintLine.name — including "" — so
    export reproduces the file byte-for-byte. The UI shows the brand name
    when a line name is empty.
  - SKU may be empty (keyed by name instead) or carry trailing whitespace.
  - Size has variants like "17|18 ml"; preserved verbatim.
  - Count can be > 1.

Never blind-overwrite: import produces an added/changed/removed diff and
only a separate confirm call applies it. "Removed" only ever targets paints
whose source starts with "PaintRack" — manually added paints are never
deleted by an import.
"""
import colorsys
import csv
import io
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.painting.models import Paint, PaintBrand, PaintLine
from app.painting.schemas import HEX_PATTERN, derive_matchable
from app.painting.services.validation import validate_code

EXPECTED_HEADER = ["Brand", "SKU", "Paint Name", "Paint Class", "Size", "Count"]
# Our extension (#255): an optional swatch color. Real PaintRack exports are
# 6-column; ours are 7. The importer accepts both.
EXTENDED_HEADER = EXPECTED_HEADER + ["Color"]

IMPORT_SOURCE_PREFIX = "PaintRack"


class PaintRackFormatError(ValueError):
    """The uploaded file does not look like a PaintRack export."""


@dataclass(frozen=True)
class CsvRow:
    brand: str
    code: str          # SKU, stripped; may be ""
    name: str
    paint_class: str   # maps to PaintLine.name verbatim; may be ""
    size: str
    count: int
    color: str = ""    # normalized "#rrggbb" or "" (6-col files / empty cell)

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity of a paint across imports: brand + class + SKU, falling
        back to the name when the SKU is empty (e.g. Dirty Down)."""
        code = self.code.lower() or f"name:{self.name.lower()}"
        return (self.brand.lower(), self.paint_class.lower(), code)


_HEX_RE = re.compile(HEX_PATTERN)  # same contract as the paint.hex schema field
_RGB_RE = re.compile(r"^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_HSV_RE = re.compile(
    r"^hsv\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$", re.IGNORECASE
)


def parse_color(value: str) -> str:
    """Normalize a Color cell to "#rrggbb". Accepts #RRGGBB, rgb(0-255,..),
    or hsv(0-360, 0-100, 0-100); "" passes through (no swatch). Raises
    ValueError on anything else."""
    value = value.strip()
    if not value:
        return ""
    if _HEX_RE.match(value):
        return value.lower()
    if m := _RGB_RE.match(value):
        r, g, b = (int(x) for x in m.groups())
        if max(r, g, b) > 255:
            raise ValueError(f"rgb() components must be 0-255: {value!r}")
        return f"#{r:02x}{g:02x}{b:02x}"
    if m := _HSV_RE.match(value):
        h, s, v = (float(x) for x in m.groups())
        if h > 360 or s > 100 or v > 100:
            raise ValueError(f"hsv() expects H 0-360, S/V 0-100: {value!r}")
        r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
        return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
    raise ValueError(f"Color {value!r} is not #RRGGBB, rgb(r,g,b), or hsv(h,s,v)")


def parse_paintrack_csv(text: str) -> list[CsvRow]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))  # strip BOM if present
    try:
        header = next(reader)
    except StopIteration:
        raise PaintRackFormatError("The file is empty")
    header = [h.strip() for h in header]
    if header not in (EXPECTED_HEADER, EXTENDED_HEADER):
        raise PaintRackFormatError(
            f"Unexpected header {header!r} — expected {EXPECTED_HEADER!r}"
            f" (optionally + ['Color'])"
        )
    width = len(header)

    rows: list[CsvRow] = []
    seen_keys: dict[tuple[str, str, str], int] = {}  # identity -> first line seen
    for n, raw in enumerate(reader, start=2):
        if not raw or not any(cell.strip() for cell in raw):
            continue
        if len(raw) != width:
            raise PaintRackFormatError(f"Line {n}: expected {width} columns, got {len(raw)}")
        brand, sku, name, paint_class, size, count = (cell.strip() for cell in raw[:6])
        if not brand or not name:
            raise PaintRackFormatError(f"Line {n}: Brand and Paint Name are required")
        try:
            count_n = int(count) if count else 1
        except ValueError:
            raise PaintRackFormatError(f"Line {n}: Count {count!r} is not a number")
        try:
            color = parse_color(raw[6]) if width == 7 else ""
        except ValueError as e:
            raise PaintRackFormatError(f"Line {n}: {e}")
        row = CsvRow(brand=brand, code=sku, name=name,
                     paint_class=paint_class, size=size, count=count_n,
                     color=color)
        # Reject duplicate paint identities up front: applying them would
        # double-insert (compute_diff emits each as added) or collapse onto
        # one DB row, both of which break (line, code) uniqueness (#442).
        if row.key in seen_keys:
            ident = sku or f"name '{name}'"
            raise PaintRackFormatError(
                f"Line {n}: duplicate paint {ident} for {brand}"
                f"{f' / {paint_class}' if paint_class else ''}"
                f" — first seen on line {seen_keys[row.key]}"
            )
        seen_keys[row.key] = n
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Finish inference
# ---------------------------------------------------------------------------

# PaintRack carries no finish; infer one from brand/class/name keywords so the
# derived `matchable` flag is honest. Checked in order — first hit wins; the
# user can correct any paint afterwards in the Paint Shelf.
_MEDIUM_WORDS = ("medium", "varnish", "cleaner", "stabilizer", "retarder",
                 "thinner", "thinning", "putty", "cement")
_PRIMER_WORDS = ("primer", "prime", "surfacer", "undercoat")
_METAL_WORDS = ("silver", "gold", "bronze", "copper", "brass", "chrome",
                "steel", "iron", "metal", "aluminium", "aluminum", "gunmetal",
                "mithril", "magnesium", "chipping")


def infer_finish(brand: str, paint_class: str, name: str) -> str:
    b, c, n = brand.lower(), paint_class.lower(), name.lower()

    if any(w in n for w in _MEDIUM_WORDS):
        return "medium"
    if any(w in c for w in _PRIMER_WORDS) or any(w in n for w in _PRIMER_WORDS):
        return "primer"
    if "texture" in c or "basing" in c:
        return "texture"
    if "pigment" in c:
        return "pigment"
    if "fluorescent" in c or "fluorescent" in n:
        return "fluor"
    if ("wash" in c or "wash" in n or "speedpaint" in c or "shade" in c
            or "shade" in n or n.endswith(" tone") or "panel line" in c):
        return "wash"
    if "ink" in b or "transparent" in c:
        return "ink"
    if ("metallic" in c or "metal color" in c or "turboshift" in c
            or any(w in n for w in _METAL_WORDS)):
        return "metallic"
    return "matte"


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def _db_paints_by_key(db: Session) -> dict[tuple[str, str, str], Paint]:
    out: dict[tuple[str, str, str], Paint] = {}
    rows = (
        db.query(Paint, PaintLine, PaintBrand)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .all()
    )
    for paint, line, brand in rows:
        # Empty-SKU paints are stored with a "name:<name>" code, which is
        # exactly the CsvRow.key fallback form — so they compare directly.
        key = (brand.name.lower(), line.name.lower(), paint.code.lower())
        out[key] = paint
    return out


def _row_dict(row: CsvRow) -> dict:
    return {
        "brand": row.brand, "code": row.code, "name": row.name,
        "paint_class": row.paint_class, "size": row.size, "count": row.count,
        "color": row.color,
    }


def _line_patterns(db: Session) -> dict[tuple[str, str], str]:
    """(brand, line) → code_pattern for existing lines that declare one."""
    rows = (
        db.query(PaintLine, PaintBrand)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .filter(PaintLine.code_pattern.isnot(None))
        .all()
    )
    return {(b.name.lower(), l.name.lower()): l.code_pattern for l, b in rows}


def compute_diff(db: Session, rows: list[CsvRow]) -> dict:
    """added: CSV rows with no matching paint; changed: key matches but
    name/size/count differ; removed: previously-imported paints absent from
    the CSV. Manually added paints (source not PaintRack*) are never removed.

    warnings (#244): rows whose existing line declares a code_pattern the SKU
    doesn't match. Informational only — the import still applies; rows for
    lines the import would create are never flagged (new lines carry no
    pattern)."""
    existing = _db_paints_by_key(db)
    patterns = _line_patterns(db)
    warnings = []
    for row in rows:
        pattern = patterns.get((row.brand.lower(), row.paint_class.lower()))
        if pattern is None:
            continue
        message = validate_code(row.code, pattern)
        if message is not None:
            warnings.append({
                "brand": row.brand, "code": row.code, "name": row.name,
                "paint_class": row.paint_class, "message": message,
            })
    csv_keys = set()
    added, changed = [], []

    for row in rows:
        csv_keys.add(row.key)
        paint = existing.get(row.key)
        if paint is None:
            added.append(_row_dict(row))
            continue
        deltas = {}
        if paint.name != row.name:
            deltas["name"] = {"from": paint.name, "to": row.name}
        if (paint.size or "") != row.size:
            deltas["size"] = {"from": paint.size or "", "to": row.size}
        if (paint.count if paint.count is not None else 1) != row.count:
            deltas["count"] = {"from": paint.count or 1, "to": row.count}
        # An empty color never clears a swatch (real PaintRack files carry no
        # color); compare case-insensitively so a stored #2A2A2A round-trips.
        if row.color and (paint.hex or "").lower() != row.color:
            deltas["color"] = {"from": paint.hex or "", "to": row.color}
        if deltas:
            changed.append({**_row_dict(row), "paint_id": paint.id, "changes": deltas})

    removed = [
        {"paint_id": paint.id, "brand": key[0], "code": paint.code,
         "name": paint.name, "paint_class": key[1]}
        for key, paint in existing.items()
        if key not in csv_keys
        and (paint.source or "").startswith(IMPORT_SOURCE_PREFIX)
    ]
    return {"added": added, "changed": changed, "removed": removed, "warnings": warnings}


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _resolve_line(db: Session, cache: dict, brand_name: str, class_name: str) -> PaintLine:
    key = (brand_name.lower(), class_name.lower())
    if key in cache:
        return cache[key]
    brand = db.query(PaintBrand).filter(PaintBrand.name.ilike(brand_name)).first()
    if brand is None:
        brand = PaintBrand(name=brand_name)
        db.add(brand)
        db.flush()
    line = (
        db.query(PaintLine)
        .filter(PaintLine.brand_id == brand.id, PaintLine.name.ilike(class_name))
        .first()
    )
    # Empty class is a real line name ("" — PaintRack's unclassified bucket);
    # ilike("") matches only "", which is what we want.
    if line is None and class_name == "":
        line = (
            db.query(PaintLine)
            .filter(PaintLine.brand_id == brand.id, PaintLine.name == "")
            .first()
        )
    if line is None:
        line = PaintLine(brand_id=brand.id, name=class_name)
        db.add(line)
        db.flush()
    cache[key] = line
    return line


def apply_diff(
    db: Session,
    rows: list[CsvRow],
    *,
    apply_added: bool = True,
    apply_changed: bool = True,
    apply_removed: bool = False,
    source_label: str,
) -> dict:
    """Recompute the diff against current data and apply the selected parts.
    Returns counts. Stateless by design: the confirm endpoint re-sends the
    CSV, so nothing is trusted from the preview round-trip."""
    diff = compute_diff(db, rows)
    rows_by_key = {row.key: row for row in rows}
    counts = {"added": 0, "changed": 0, "removed": 0}
    line_cache: dict = {}

    if apply_added:
        for item in diff["added"]:
            row = rows_by_key[CsvRow(**item).key]
            line = _resolve_line(db, line_cache, row.brand, row.paint_class)
            finish = infer_finish(row.brand, row.paint_class, row.name)
            db.add(Paint(
                paint_line_id=line.id,
                code=row.code or f"name:{row.name}",
                name=row.name,
                hex=row.color or None,
                finish=finish,
                matchable=derive_matchable(finish),
                owned=True,
                size=row.size or None,
                count=row.count,
                source=source_label,
            ))
            counts["added"] += 1

    if apply_changed:
        for item in diff["changed"]:
            paint = db.get(Paint, item["paint_id"])
            row = rows_by_key[CsvRow(
                brand=item["brand"], code=item["code"], name=item["name"],
                paint_class=item["paint_class"], size=item["size"], count=item["count"],
            ).key]
            paint.name = row.name
            paint.size = row.size or None
            paint.count = row.count
            if row.color:  # empty color leaves an existing swatch alone
                paint.hex = row.color
            paint.source = source_label
            counts["changed"] += 1

    if apply_removed:
        for item in diff["removed"]:
            paint = db.get(Paint, item["paint_id"])
            if paint is not None:
                db.delete(paint)
                counts["removed"] += 1

    db.commit()
    return counts


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_csv(db: Session) -> str:
    """PaintRack-format export plus the Color extension column (#255).
    Writes PaintLine.name verbatim as Paint Class (including empty) and the
    stored hex as Color, so export → import yields an empty diff (#243)."""
    rows = (
        db.query(Paint, PaintLine, PaintBrand)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .order_by(PaintBrand.name, Paint.code, Paint.name)
        .all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(EXTENDED_HEADER)
    for paint, line, brand in rows:
        code = "" if paint.code.startswith("name:") else paint.code
        writer.writerow([
            brand.name, code, paint.name, line.name,
            paint.size or "", paint.count if paint.count is not None else 1,
            paint.hex or "",
        ])
    return buf.getvalue()
