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
import csv
import io
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.painting.models import Paint, PaintBrand, PaintLine
from app.painting.schemas import derive_matchable

EXPECTED_HEADER = ["Brand", "SKU", "Paint Name", "Paint Class", "Size", "Count"]

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

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity of a paint across imports: brand + class + SKU, falling
        back to the name when the SKU is empty (e.g. Dirty Down)."""
        code = self.code.lower() or f"name:{self.name.lower()}"
        return (self.brand.lower(), self.paint_class.lower(), code)


def parse_paintrack_csv(text: str) -> list[CsvRow]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))  # strip BOM if present
    try:
        header = next(reader)
    except StopIteration:
        raise PaintRackFormatError("The file is empty")
    if [h.strip() for h in header] != EXPECTED_HEADER:
        raise PaintRackFormatError(
            f"Unexpected header {header!r} — expected {EXPECTED_HEADER!r}"
        )

    rows: list[CsvRow] = []
    for n, raw in enumerate(reader, start=2):
        if not raw or not any(cell.strip() for cell in raw):
            continue
        if len(raw) != len(EXPECTED_HEADER):
            raise PaintRackFormatError(f"Line {n}: expected 6 columns, got {len(raw)}")
        brand, sku, name, paint_class, size, count = (cell.strip() for cell in raw)
        if not brand or not name:
            raise PaintRackFormatError(f"Line {n}: Brand and Paint Name are required")
        try:
            count_n = int(count) if count else 1
        except ValueError:
            raise PaintRackFormatError(f"Line {n}: Count {count!r} is not a number")
        rows.append(CsvRow(brand=brand, code=sku, name=name,
                           paint_class=paint_class, size=size, count=count_n))
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
    }


def compute_diff(db: Session, rows: list[CsvRow]) -> dict:
    """added: CSV rows with no matching paint; changed: key matches but
    name/size/count differ; removed: previously-imported paints absent from
    the CSV. Manually added paints (source not PaintRack*) are never removed."""
    existing = _db_paints_by_key(db)
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
        if deltas:
            changed.append({**_row_dict(row), "paint_id": paint.id, "changes": deltas})

    removed = [
        {"paint_id": paint.id, "brand": key[0], "code": paint.code,
         "name": paint.name, "paint_class": key[1]}
        for key, paint in existing.items()
        if key not in csv_keys
        and (paint.source or "").startswith(IMPORT_SOURCE_PREFIX)
    ]
    return {"added": added, "changed": changed, "removed": removed}


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
    """PaintRack-format export. Writes PaintLine.name verbatim as Paint Class
    (including empty), so export → import yields an empty diff (#243)."""
    rows = (
        db.query(Paint, PaintLine, PaintBrand)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .order_by(PaintBrand.name, Paint.code, Paint.name)
        .all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(EXPECTED_HEADER)
    for paint, line, brand in rows:
        code = "" if paint.code.startswith("name:") else paint.code
        writer.writerow([
            brand.name, code, paint.name, line.name,
            paint.size or "", paint.count if paint.count is not None else 1,
        ])
    return buf.getvalue()
